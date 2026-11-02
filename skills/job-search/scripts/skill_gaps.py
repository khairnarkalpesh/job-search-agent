#!/usr/bin/env python
"""Which missing skills cost you the most, counted over your saved search results.

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

from job_storage import read_json
from skill_taxonomy import DATA_DIR

REQUIRED_WEIGHT = 3
OTHER_WEIGHT = 1


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
    for job in counted:
        required_here = set(job.get("missing_required_skills") or [])
        required.update(required_here)
        mentioned.update(set(job.get("missing_skills") or []) - required_here)
    ranking = [{"skill": skill, "required_by": required[skill], "mentioned_by": mentioned[skill],
                "weight": required[skill] * REQUIRED_WEIGHT + mentioned[skill] * OTHER_WEIGHT}
               for skill in set(required) | set(mentioned)]
    ranking.sort(key=lambda item: (-item["weight"], item["skill"].lower()))
    return ranking, len(counted)


def run(arguments) -> int:
    data_dir = Path(arguments.data_dir) if arguments.data_dir else DATA_DIR
    jobs = read_json(data_dir / "job_results.json", [])
    if not jobs:
        print("No saved results yet. Run a search first (/job-search).", file=sys.stderr)
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
    print("| Skill | Required by | Mentioned by |\n|---|---|---|")
    for item in ranking:
        print(f"| {item['skill']} | {item['required_by']} | {item['mentioned_by']} |")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
