#!/usr/bin/env python
"""ATS Readiness: how well a resume file can be parsed and understood by screening software.

    python scripts/resume_ats.py --resume resume.pdf
    python scripts/resume_ats.py --resume resume.docx --url https://jobs.lever.co/acme/1234
    python scripts/resume_ats.py --resume resume.docx --text-file job.txt --title "Backend Engineer"

Without a job it checks parsing, structure, section quality and formatting. With a job it
also checks keyword coverage and required skills, and prints the Job Match score beside
it as a separate number. The report is saved to ats_report.json in the data folder; it
holds which contact fields were found, never their values.
"""
from __future__ import annotations

import argparse
import json
import sys

from ats_readiness import assess_resume, format_ats_report, format_separate_scores
from http_client import FetchError
from job_storage import load_preferences, write_json
from match_job import add_job_arguments, load_profile, read_job
from resume_layout import inspect_resume
from resume_parser import SYNTHETIC_MARKER, ResumeParseError
from score_jobs import score_job
from search_jobs import choose_data_dir
from target_roles import candidate_skill_set

REPORT_FILE = "ats_report.json"


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a resume's ATS Readiness, optionally for one job.")
    parser.add_argument("--resume", required=True, help="The resume file: PDF, DOCX, TXT or Markdown")
    add_job_arguments(parser, required=False)
    parser.add_argument("--profile", help="candidate_profile.json to use (default: the saved one)")
    parser.add_argument("--data-dir", help="Where to save the report (default: your data folder)")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    return parser.parse_args(argv)


def run(arguments: argparse.Namespace, client=None) -> int:
    try:
        document = inspect_resume(arguments.resume)
    except ResumeParseError as error:
        print(f"Could not check the resume: {error}", file=sys.stderr)
        return 2
    try:
        profile = load_profile(arguments.profile)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read the profile: {error}. Pass a candidate_profile.json, not a resume.", file=sys.stderr)
        return 2
    job = None
    if arguments.url or arguments.text_file:
        try:
            job = read_job(arguments, client)
        except FetchError as error:
            print(f"Could not read that job: {error}", file=sys.stderr)
            return 1
        except (OSError, ValueError) as error:
            print(f"Could not read the job text: {error}", file=sys.stderr)
            return 2

    report = assess_resume(document, job, candidate_skill_set(profile) if profile else set())
    data_dir = choose_data_dir(arguments, {"synthetic": SYNTHETIC_MARKER in document.text.upper()})
    write_json(data_dir / REPORT_FILE, report)
    scored = score_job(job, profile, load_preferences()) if job and profile else None
    if arguments.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if scored:
        print(format_separate_scores(report, scored) + "\n")
    elif job:
        print("No saved profile, so there is no Job Match score beside this one. Run /job-profile for that.\n")
    print(format_ats_report(report))
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
