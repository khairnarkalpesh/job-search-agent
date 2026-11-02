#!/usr/bin/env python
"""Find public jobs matching a resume.

    python scripts/search_jobs.py --resume resume.pdf --limit 30
    python scripts/search_jobs.py --resume resume.pdf --location Remote --source greenhouse,lever,remotive --min-score 80

Sources are company applicant-tracking systems (Greenhouse, Lever, Ashby, Workable,
SmartRecruiters), job portals with public APIs (Remotive, Remote OK, Himalayas,
Arbeitnow) and company career websites. All are used unless --source narrows them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deduplicate import deduplicate_jobs
from http_client import FetchError, HttpClient
from job_discovery import (DuckDuckGoSearch, boards_from_urls, build_search_queries, discover_board_urls)
from job_storage import JobStore, load_preferences, save_preferences
from location_matching import candidate_targets, match_location
from normalize_jobs import enrich_job
from resume_parser import ResumeParseError, load_profile_from_resume
from results_report import format_report
from score_jobs import score_job
from skill_taxonomy import DATA_DIR, SYNTHETIC_DATA_DIR, USER_HOME, title_family, taxonomy
from sources import ATS_SOURCES, SOURCES, JobBoard

DEFAULT_MINIMUM_SCORE = 60
EXCLUDED_FAMILIES = {"not_engineering", "other_engineering", "management", None}
UNSPECIFIC_FAMILIES = {"general_software", "unspecified_engineer"}


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find public jobs that match a resume.")
    parser.add_argument("--resume", help="PDF, DOCX, TXT or Markdown resume")
    parser.add_argument("--profile", help="Use this reviewed candidate_profile.json instead of parsing a resume")
    parser.add_argument("--limit", type=int, default=20, help="How many jobs to show (default 20)")
    parser.add_argument("--location", default="", help='Comma-separated, e.g. "Remote,Bangalore"')
    parser.add_argument("--role", default="", help='Only this kind of role, e.g. "Backend Engineer"')
    parser.add_argument("--source", default="", help=f"Comma-separated, from: {','.join(SOURCES)} (default: all)")
    parser.add_argument("--min-score", type=int, help=f"Hide lower scores (default {DEFAULT_MINIMUM_SCORE})")
    parser.add_argument("--remote", action="store_true", help="Only remote jobs")
    parser.add_argument("--all", action="store_true", help="Show every scored job, whatever its score")
    parser.add_argument("--new-only", action="store_true", help="Hide jobs seen on earlier runs")
    parser.add_argument("--board", action="append", default=[], metavar="SOURCE:SLUG",
                        help="Add a company board, e.g. lever:acme or ashby:acme (repeatable)")
    parser.add_argument("--urls-file", help="Text file of job or board URLs, one per line")
    parser.add_argument("--extract-only", action="store_true", help="Build the profile and stop")
    parser.add_argument("--plan", action="store_true", help="Print web search queries as JSON and stop")
    parser.add_argument("--save-preferences", action="store_true", help="Save this run's filters as preferences")
    parser.add_argument("--data-dir", help="Where to store results (default: data/)")
    return parser.parse_args(argv)


def progress(message: str) -> None:
    print(message, flush=True)


def load_candidate(arguments: argparse.Namespace) -> dict:
    if arguments.profile:
        return json.loads(Path(arguments.profile).read_text(encoding="utf-8"))
    if arguments.resume:
        return load_profile_from_resume(arguments.resume)
    saved_profile = JobStore(Path(arguments.data_dir) if arguments.data_dir else DATA_DIR).load_profile()
    if saved_profile:
        return saved_profile
    raise ResumeParseError("No resume given. Use --resume path/to/resume.pdf")


def choose_data_dir(arguments: argparse.Namespace, profile: dict) -> Path:
    """Synthetic test data is kept out of the real data folder."""
    data_dir = Path(arguments.data_dir).resolve() if arguments.data_dir else None
    if profile.get("synthetic"):
        if data_dir is None or data_dir == DATA_DIR.resolve():
            return SYNTHETIC_DATA_DIR
        return data_dir
    return data_dir or DATA_DIR


def choose_sources(arguments: argparse.Namespace, preferences: dict) -> list[str]:
    requested = [name.strip().lower() for name in arguments.source.split(",") if name.strip()]
    sources = requested or preferences.get("preferred_sources") or list(SOURCES)
    unknown_sources = [name for name in sources if name not in SOURCES]
    if unknown_sources:
        raise SystemExit(f"Unknown source: {', '.join(unknown_sources)}. Choose from {', '.join(SOURCES)}.")
    return sources


def parse_board_argument(value: str) -> JobBoard:
    source, _, slug = value.partition(":")
    if source not in SOURCES or not slug:
        raise SystemExit(f"Bad --board value '{value}'. Use source:slug, e.g. lever:acme")
    return JobBoard(source, slug)


def portal_search_terms(arguments, profile: dict) -> list[str]:
    return [arguments.role] if arguments.role else [role["title"] for role in profile.get("target_roles", [])]


def collect_boards(arguments, store: JobStore, profile: dict, sources: list[str], client: HttpClient) -> tuple[list[JobBoard], list[str]]:
    warnings: list[str] = []
    urls: list[str] = []
    if arguments.urls_file:
        urls = [line.strip() for line in Path(arguments.urls_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    boards = [board for board in map(parse_board_argument, arguments.board) if board.source in sources]
    boards += boards_from_urls(urls, sources)
    boards += [board for board in store.known_boards() if board.source in sources]
    wanted_ats = [name for name in sources if name in ATS_SOURCES]
    if wanted_ats and not any(board.source in ATS_SOURCES for board in boards):
        queries = build_search_queries(profile, wanted_ats, arguments.role, arguments.location, arguments.remote)
        found_urls, warning = discover_board_urls(DuckDuckGoSearch(client), queries)
        if warning:
            warnings.append(warning)
        boards += boards_from_urls(found_urls, wanted_ats)
    for name in sources:
        boards += SOURCES[name].boards_for(portal_search_terms(arguments, profile))
    unique_boards = {board.key(): board for board in boards}
    return list(unique_boards.values()), warnings


def fetch_all_jobs(boards: list[JobBoard], client: HttpClient) -> tuple[list[dict], list[JobBoard], list[str]]:
    jobs: list[dict] = []
    working_boards: list[JobBoard] = []
    unavailable: list[str] = []
    for position, board in enumerate(boards, start=1):
        try:
            board_jobs = SOURCES[board.source].fetch_board(board, client)
        except FetchError as error:
            unavailable.append(f"{board.source}/{board.slug}: source unavailable ({error.kind})")
            continue
        progress(f"  [{position}/{len(boards)}] {SOURCES[board.source].label}/{board.slug}: {len(board_jobs)} listings")
        jobs.extend(board_jobs)
        working_boards.append(board)
    return jobs, working_boards, unavailable


def allowed_role_families(profile: dict, preferences: dict, role_filter: str) -> set[str]:
    if role_filter:
        return {title_family(role_filter)} - {None}
    families = {role["family"] for role in profile.get("target_roles", [])}
    families |= {title_family(role) for role in preferences.get("target_roles") or []} - {None}
    return families


def is_relevant(job: dict, families: set[str], arguments, targets: list[str], preferences: dict) -> bool:
    family = title_family(job["title"])
    if family in EXCLUDED_FAMILIES:
        return False
    wanted_families = set(families)
    for family_name in families:
        wanted_families |= set(taxonomy()["adjacent_families"].get(family_name, []))
    if family not in wanted_families and family not in UNSPECIFIC_FAMILIES:
        return False
    if arguments.role and family not in UNSPECIFIC_FAMILIES and family not in families:
        return False
    if arguments.remote and job.get("remote") is not True:
        return False
    employment_types = preferences.get("employment_types") or []
    if employment_types and job.get("employment_type") and job["employment_type"] not in employment_types:
        return False
    if arguments.location and match_location(job, targets).status in ("mismatch", "partial"):
        return False
    return True


def persist_preferences(arguments, preferences: dict, sources: list[str]) -> None:
    updated = dict(preferences)
    if arguments.location:
        updated["target_locations"] = [part.strip() for part in arguments.location.split(",") if part.strip()]
    if arguments.role:
        updated["target_roles"] = [arguments.role]
    if arguments.min_score is not None:
        updated["minimum_match_score"] = arguments.min_score
    if arguments.source:
        updated["preferred_sources"] = sources
    if arguments.remote:
        updated["remote_preference"] = "remote_only"
    save_preferences(updated)


def run(arguments: argparse.Namespace) -> int:
    progress("Analyzing your profile...")
    try:
        profile = load_candidate(arguments)
    except (ResumeParseError, OSError, json.JSONDecodeError) as error:
        print(f"Could not load your profile: {error}", file=sys.stderr)
        return 2

    data_dir = choose_data_dir(arguments, profile)
    if profile.get("synthetic"):
        progress(f"Synthetic test resume detected. Results go to {data_dir}, apart from real data.")
    store = JobStore(data_dir)
    preferences = load_preferences()
    sources = choose_sources(arguments, preferences)
    store.save_profile(profile)
    target_titles = [role["title"] for role in profile["target_roles"]]
    progress(f"Found {len(target_titles)} relevant target roles: {', '.join(target_titles)}")
    if not target_titles:
        print("No target roles could be worked out from this resume, so there is nothing to search for. "
              "Use --role, or review the saved profile.", file=sys.stderr)
        if not arguments.role:
            return 2
    if arguments.save_preferences:
        persist_preferences(arguments, preferences, sources)
        preferences = load_preferences()
    if arguments.extract_only:
        progress(f"Profile saved to {store.profile_path}")
        return 0
    if arguments.plan:
        print(json.dumps(build_search_queries(profile, sources, arguments.role, arguments.location, arguments.remote), indent=2))
        return 0

    client = HttpClient(cache_dir=USER_HOME / "cache")
    progress(f"Searching public listings on {', '.join(SOURCES[name].label for name in sources)}...")
    boards, warnings = collect_boards(arguments, store, profile, sources, client)
    for warning in warnings:
        progress(f"Note: {warning}")
    if not boards:
        progress("No job boards to search. Web search found none, and none are saved yet.\n"
                 "Run this skill through Claude, which searches the web for boards, or add one with --board lever:company.")
        return 1

    jobs, working_boards, unavailable = fetch_all_jobs(boards, client)
    store.remember_boards([board for board in working_boards if board.source in ATS_SOURCES])
    for message in unavailable:
        progress(f"Skipped {message}")
    progress(f"Found {len(jobs)} listings on {len(working_boards)} of {len(boards)} boards")
    if not jobs:
        progress("No listings were available from any board." if not working_boards else "These boards have no open listings.")
        return 1

    targets = candidate_targets(profile, preferences, arguments.location)
    families = allowed_role_families(profile, preferences, arguments.role)
    relevant_jobs = [job for job in jobs if is_relevant(job, families, arguments, targets, preferences)]
    unique_jobs, removed_duplicates = deduplicate_jobs(relevant_jobs)
    duplicate_count = sum(removed_duplicates.values())
    progress(f"Removed {len(jobs) - len(relevant_jobs)} irrelevant jobs and {duplicate_count} duplicates")

    completed_jobs = [SOURCES[job["source"]].complete_job(job, client) for job in unique_jobs]
    scored_jobs = [score_job(enrich_job(job), profile, preferences, arguments.location) for job in completed_jobs]
    reliable_jobs = [job for job in scored_jobs if job["reliable"]]
    progress(f"Scored {len(scored_jobs)} jobs")
    if len(reliable_jobs) < len(scored_jobs):
        progress(f"{len(scored_jobs)} listings found, but only {len(reliable_jobs)} had enough information to score reliably.")

    minimum_score = arguments.min_score if arguments.min_score is not None else preferences.get("minimum_match_score") or DEFAULT_MINIMUM_SCORE
    summary = {
        "resume_synthetic": bool(profile.get("synthetic")),
        "filters": {"location": arguments.location, "role": arguments.role, "sources": sources, "remote": arguments.remote},
        "boards_searched": len(boards), "boards_unavailable": len(unavailable), "listings_found": len(jobs),
        "irrelevant_removed": len(jobs) - len(relevant_jobs), "duplicates_removed": duplicate_count,
        "scored": len(scored_jobs), "reliably_scored": len(reliable_jobs),
    }
    store.record_results(scored_jobs, summary)

    ranked_jobs = sorted(reliable_jobs, key=lambda job: job["match_score"], reverse=True)
    if arguments.new_only:
        ranked_jobs = [job for job in ranked_jobs if job["seen"] == "NEW JOB"]
    shown_jobs = ranked_jobs if arguments.all else [job for job in ranked_jobs if job["match_score"] >= minimum_score]
    summary["below_minimum_score"] = len(ranked_jobs) - len(shown_jobs)
    shown_jobs = shown_jobs[:arguments.limit]
    if not shown_jobs:
        best_score = ranked_jobs[0]["match_score"] if ranked_jobs else None
        progress(f"No jobs reached the minimum score of {minimum_score}."
                 + (f" The best was {best_score}. Use --all to see everything." if best_score is not None else ""))
        return 0
    progress("Here are your top matches\n")
    print(format_report(shown_jobs, summary))
    progress(f"\nSaved to {store.results_path}")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
