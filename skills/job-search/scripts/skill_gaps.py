#!/usr/bin/env python
"""Which missing skills cost you the most, counted over your saved search results and matched jobs.

    python scripts/skill_gaps.py
    python scripts/skill_gaps.py --min-score 50 --top 15

Only jobs that were scored reliably count. A skill required by a job weighs more than
one it only mentions, because a required gap can cap the score.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from job_storage import JobStore
from skill_taxonomy import DATA_DIR

REQUIRED_WEIGHT = 3
OTHER_WEIGHT = 1
PARTIAL_FACTOR = 0.5  # a skill partly covered by a neighbour (Docker for Kubernetes) is half as urgent
FEW_JOBS = 10  # below this many jobs, a ranking is a hint, not a pattern


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank the skills missing from your resume by how often jobs ask for them.")
    parser.add_argument("--min-score", type=int, default=40, help="Only count jobs scoring at least this (default 40)")
    parser.add_argument("--top", type=int, default=10, help="How many skills to show (default 10)")
    parser.add_argument("--json", action="store_true", help="Print the ranking as JSON")
    parser.add_argument("--data-dir", help="Where saved results live (default: your data folder)")
    return parser.parse_args(argv)


def rank_gaps(jobs: list[dict], min_score: int) -> tuple[list[dict], int]:
    counted = [job for job in jobs if job.get("reliable") and job.get("match_score", 0) >= min_score]
    required = collections.Counter()
    mentioned = collections.Counter()
    partly_required = collections.Counter()
    partly_mentioned = collections.Counter()
    close_to: dict[str, set[str]] = collections.defaultdict(set)
    for job in counted:
        for item in job.get("partial_skills", []):
            (partly_required if item["importance"] == "required" else partly_mentioned)[item["skill"]] += 1
            close_to[item["skill"]].add(item["matched_with"])
        # An either-or list is one gap, named as the listing names it: "GCP, AWS or Azure".
        # Results saved before labels existed fall back to the skill names.
        required_here = set(job.get("missing_required_labels") or job.get("missing_required_skills") or [])
        required.update(required_here)
        mentioned.update(set(job.get("missing_labels") or job.get("missing_skills") or []) - required_here)
    ranking = [{"skill": skill, "required_by": required[skill] + partly_required[skill],
                "mentioned_by": mentioned[skill] + partly_mentioned[skill],
                "partly_covered_in": partly_required[skill] + partly_mentioned[skill],
                "close_to": sorted(close_to.get(skill, ())),
                "weight": required[skill] * REQUIRED_WEIGHT + mentioned[skill] * OTHER_WEIGHT
                + PARTIAL_FACTOR * (partly_required[skill] * REQUIRED_WEIGHT + partly_mentioned[skill] * OTHER_WEIGHT)}
               for skill in set(required) | set(mentioned) | set(partly_required) | set(partly_mentioned)]
    ranking.sort(key=lambda item: (-item["weight"], item["skill"].lower()))
    return ranking, len(counted)


def run(arguments) -> int:
    data_dir = Path(arguments.data_dir) if arguments.data_dir else DATA_DIR
    jobs = JobStore(data_dir).scored_jobs()
    if not jobs:
        print("No scored jobs yet. Run a search (/job-search) or score a job you found (/job-match).", file=sys.stderr)
        return 1
    ranking, counted = rank_gaps(jobs, arguments.min_score)
    ranking = ranking[:arguments.top]
    if arguments.json:
        print(json.dumps({"jobs_counted": counted, "gaps": ranking}, indent=2))
        return 0
    if not ranking:
        print(f"No missing skills across {counted} reliably scored jobs at {arguments.min_score}+.")
        return 0
    print(f"Skills missing from your resume, across {counted} reliably scored jobs scoring {arguments.min_score}+\n")
    print("| Skill | Required by | Mentioned by | You have something close |\n|---|---|---|---|")
    for item in ranking:
        close = (f"{', '.join(item['close_to'])} (in {item['partly_covered_in']} job(s))"
                 if item["partly_covered_in"] else "")
        print(f"| {item['skill']} | {item['required_by']} | {item['mentioned_by']} | {close} |")
    if counted < FEW_JOBS:
        print(f"\nOnly {counted} job(s) counted, so this is a hint, not a pattern. Score more jobs first.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
