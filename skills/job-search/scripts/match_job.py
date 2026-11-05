#!/usr/bin/env python
"""Score one job against the saved profile.

    python scripts/match_job.py --url https://jobs.lever.co/acme/1234
    python scripts/match_job.py --text-file job.txt --title "Backend Engineer" --company Acme --location Pune
    python scripts/match_job.py --text-dir ~/.job-search-agent/data/fetched --source-name "Greenhouse"

--url works for any supported board and for company career pages with JobPosting data.
--text-file is for everything else, including LinkedIn, Naukri and Indeed: copy the
listing text into a file yourself. Nothing here logs in to or scrapes those sites.
--text-dir scores every .txt and .md file in a folder, one listing per file: the fallback
when the network is blocked and listings were fetched by hand. Closed listings are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

from ats_readiness import assess_resume, format_ats_report, format_separate_scores
from http_client import FetchError, HttpClient
from job_storage import JobStore, load_preferences, profile_warning
from location_matching import countries_in
from normalize_jobs import closed_listing_reason, enrich_job, make_job
from results_report import format_job_details, format_results_table
from resume_layout import inspect_resume
from resume_parser import ResumeParseError
from score_jobs import score_job
from skill_taxonomy import DATA_DIR, SYNTHETIC_DATA_DIR, USER_HOME
from sources import SOURCES, board_from_url
from target_roles import candidate_skill_set


def add_job_arguments(parser: argparse.ArgumentParser, required: bool, batch: bool = False) -> None:
    """The flags that name one job. Shared with resume_ats.py and resume_optimize.py."""
    given = parser.add_mutually_exclusive_group(required=required)
    given.add_argument("--url", help="A job's URL on a supported board or a company career page")
    given.add_argument("--text-file", help="A text file holding the job listing, copied by you")
    if batch:
        given.add_argument("--text-dir", help="A folder of listing text files, one job per file, to score together")
    parser.add_argument("--title", default="", help="Job title (text files only; default: first line)")
    parser.add_argument("--company", default="", help="Company (text files only)")
    parser.add_argument("--location", default="", help="Location as the listing states it (text files only)")
    parser.add_argument("--source-name", default="pasted", help='Where the text came from, e.g. "LinkedIn"')


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score one job against your saved profile.")
    add_job_arguments(parser, required=True, batch=True)
    parser.add_argument("--profile", help="candidate_profile.json to use (default: the saved one)")
    parser.add_argument("--resume", help="Also check this resume file's ATS readiness for the job")
    parser.add_argument("--json", action="store_true", help="Print the scored job as JSON")
    return parser.parse_args(argv)


def _url_names_job(url: str, job_id: str) -> bool:
    # The id is a path segment, sometimes followed by the title: /744000159066799-backend-engineer
    segments = [segment for segment in urllib.parse.urlsplit(url).path.split("/") if segment]
    return bool(job_id) and any(segment == job_id or segment.startswith(f"{job_id}-") for segment in segments)


def job_from_url(url: str, client) -> dict:
    board = board_from_url(url)
    if board is None:
        raise FetchError("not_found", url, "not a web address")
    source = SOURCES[board.source]
    jobs = source.fetch_board(board, client)
    if board.source == "generic":
        job = jobs[0] if len(jobs) == 1 else next((item for item in jobs if item["source_url"] == url), None)
    else:
        job = next((item for item in jobs if _url_names_job(url, item["job_id"].rsplit(":", 1)[-1])), None)
    if job is None:
        raise FetchError("not_found", url, f"no open job with this address on the {source.label} board")
    return source.complete_job(job, client)


_LABELLED_FIELD = re.compile(r"^\s*(job title|title|role|position|company|employer|organi[sz]ation|location|"
                            r"job location|work location)\s*[:\-–]\s*(.+?)\s*$", re.IGNORECASE)
_FIELD_NAMES = {"job title": "title", "title": "title", "role": "title", "position": "title", "company": "company",
                "employer": "company", "organisation": "company", "organization": "company", "location": "location",
                "job location": "location", "work location": "location"}
# LinkedIn puts "Company · City, State, Country · 2 days ago" under the title.
_DOT_LINE = re.compile(r"^\s*([^·•|]{2,60}?)\s*[·•|]\s*([^·•|]{2,80}?)(?:\s*[·•|].*)?$")
_HEADER_LINES = 6


def listing_fields(text: str) -> dict[str, str]:
    """Title, company and location as a pasted listing states them, when it states them.

    Reads labelled lines ("Location: Pune") anywhere, and LinkedIn's "Company · Location"
    line near the top. A field the text does not state is left out, never guessed.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    for line in lines:
        labelled = _LABELLED_FIELD.match(line)
        if labelled:
            fields.setdefault(_FIELD_NAMES[labelled.group(1).lower()], labelled.group(2))
    for line in lines[1:_HEADER_LINES]:
        dotted = _DOT_LINE.match(line)
        if dotted and countries_in(dotted.group(2)) | ({"remote"} if "remote" in dotted.group(2).lower() else set()):
            fields.setdefault("company", dotted.group(1))
            fields.setdefault("location", dotted.group(2))
            break
    if lines:
        fields.setdefault("title", lines[0].strip())
    return fields


def job_from_text(text_file: str, title: str = "", company: str = "", location: str = "",
                  source_name: str = "pasted") -> dict:
    """A job from listing text the user saved. Flags given win; otherwise the text's own fields."""
    text = Path(text_file).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("the job text file is empty")
    closed = closed_listing_reason(text)
    if closed:
        raise ValueError(f"this listing has closed: {closed}")
    stated = listing_fields(text)
    text_id = hashlib.sha1(text.encode()).hexdigest()[:16]
    job = make_job(source="manual", board=source_name, job_id=text_id,
                   title=title or stated.get("title", ""), company=company or stated.get("company", ""),
                   location=location or stated.get("location", ""), description=text, url="")
    # The text alone names the job: the same listing pasted twice under different --source-name
    # values is one job, so /job-gaps does not count it twice.
    job["job_id"] = f"manual:text:{text_id}"
    return job


def read_job(arguments: argparse.Namespace, client=None) -> dict:
    """The job named by add_job_arguments' flags, enriched and ready to score.

    Raises FetchError for a URL that cannot be read, OSError or ValueError for a bad text file.
    """
    if arguments.text_file:
        job = job_from_text(arguments.text_file, arguments.title, arguments.company, arguments.location,
                            arguments.source_name)
    else:
        job = job_from_url(arguments.url, client or HttpClient(cache_dir=USER_HOME / "cache"))
    return enrich_job(job)


def load_profile(path: str | None) -> dict | None:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return JobStore(DATA_DIR).load_profile()


TEXT_SUFFIXES = (".txt", ".md")


def score_folder(arguments, profile: dict, store: JobStore) -> int:
    """Score every listing file in a folder, best first. Closed and unreadable files are listed, not scored."""
    folder = Path(arguments.text_dir).expanduser()
    files = sorted(path for path in folder.glob("*") if path.suffix.lower() in TEXT_SUFFIXES) if folder.is_dir() else []
    if not files:
        print(f"No .txt or .md listings in {folder}.", file=sys.stderr)
        return 2
    preferences = load_preferences()
    scored, skipped = [], []
    for path in files:
        try:
            job = enrich_job(job_from_text(str(path), source_name=arguments.source_name))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            skipped.append(f"{path.name}: {error}")
            continue
        scored.append({**score_job(job, profile, preferences), "seen": path.name})
        store.record_match(scored[-1])
    scored.sort(key=lambda job: job["match_score"], reverse=True)
    if arguments.json:
        print(json.dumps({"jobs": scored, "skipped": skipped}, indent=2, ensure_ascii=False))
        return 0 if scored else 1
    if scored:
        print(format_results_table(scored).replace("| Seen |", "| File |"))
        rough = [job["seen"] for job in scored if not job["reliable"]]
        if rough:
            print(f"\nRough guide only (short listing or few skills named): {', '.join(rough)}")
    if skipped:
        print("\nNot scored:\n" + "\n".join(f"  - {item}" for item in skipped))
    print(f"\n{len(scored)} scored, {len(skipped)} skipped. For one job's breakdown: match_job.py --text-file <file>")
    return 0 if scored else 1


def run(arguments, client=None) -> int:
    try:
        profile = load_profile(arguments.profile)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read the profile: {error}. Pass a candidate_profile.json, not a resume.", file=sys.stderr)
        return 2
    if not profile:
        print("No saved profile yet. Run /job-profile (search_jobs.py --resume ... --extract-only) first.",
              file=sys.stderr)
        return 2
    if getattr(arguments, "text_dir", None):
        if profile_warning(profile):
            print(profile_warning(profile), file=sys.stderr)
        return score_folder(arguments, profile, JobStore(SYNTHETIC_DATA_DIR if profile.get("synthetic") else DATA_DIR))
    try:
        job = read_job(arguments, client)
    except FetchError as error:
        print(f"Could not read that job: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"Could not read the job text: {error}", file=sys.stderr)
        return 2
    ats_report = None
    if arguments.resume:
        try:
            ats_report = assess_resume(inspect_resume(arguments.resume), job, candidate_skill_set(profile))
        except ResumeParseError as error:
            print(f"Could not check the resume: {error}", file=sys.stderr)
            return 2
    if profile_warning(profile):
        print(profile_warning(profile), file=sys.stderr)
    scored = score_job(job, profile, load_preferences())
    JobStore(SYNTHETIC_DATA_DIR if profile.get("synthetic") else DATA_DIR).record_match(scored)
    if arguments.json:
        print(json.dumps({**scored, "ats_readiness": ats_report} if ats_report else scored, indent=2, ensure_ascii=False))
        return 0
    if not scored["reliable"]:
        print("Note: the listing is short or names few skills, so this score is a rough guide only.\n")
    details = format_job_details(scored, 1)
    if job["source"] == "manual":
        details = details.replace("Listing on manual: ", f"Source: {arguments.source_name} (pasted text)").rstrip()
    print(details)
    if ats_report:
        print("\n" + format_separate_scores(ats_report, scored) + "\n\n" + format_ats_report(ats_report))
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
