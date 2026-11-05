#!/usr/bin/env python
"""Track the jobs you apply to: applied, interviewing, offer, rejected, with dates and notes.

    python scripts/applications.py list [--status interviewing]
    python scripts/applications.py add <job url or id> [--status applied] [--date 2026-11-02] [--note "..."]
    python scripts/applications.py add <job url> --title "Frontend Engineer" --company Acme
    python scripts/applications.py update <job url or id> --status interviewing --note "Round 1 on Friday"
    python scripts/applications.py remove <job url or id>

A job already scored by /job-search or /job-match is found by its URL or id, and its title,
company and score are filled in from there. Any other job needs --title and --company.
The status is also written to the search history, so later searches keep it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from pathlib import Path

from job_storage import JobStore, read_json, write_json
from skill_taxonomy import DATA_DIR, today

STATUSES = ["saved", "applied", "interviewing", "offer", "rejected", "withdrawn"]
CLOSED_STATUSES = {"offer", "rejected", "withdrawn"}
FOLLOW_UP_DAYS = 14  # an application with no news for this long is worth a follow-up
APPLICATIONS_FILE = "applications.json"


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track the jobs you apply to.")
    parser.add_argument("--data-dir", help="Where your data lives (default: your data folder)")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Show tracked applications")
    listing.add_argument("--status", choices=STATUSES)
    for name in ("add", "update"):
        command = commands.add_parser(name)
        command.add_argument("job", help="The job's URL, or its id from the saved results")
        command.add_argument("--status", choices=STATUSES, default="applied" if name == "add" else None,
                             required=name == "update")
        command.add_argument("--date", help="When it happened, YYYY-MM-DD (default: today)")
        command.add_argument("--note", default="", help="Anything worth remembering")
        if name == "add":
            command.add_argument("--title", default="", help="Job title (for a job not scored here)")
            command.add_argument("--company", default="", help="Company (for a job not scored here)")
    remove = commands.add_parser("remove")
    remove.add_argument("job")
    return parser.parse_args(argv)


class Tracker:
    def __init__(self, data_dir: Path):
        self.store = JobStore(data_dir)
        self.path = data_dir / APPLICATIONS_FILE

    def load(self) -> dict[str, dict]:
        return {entry["id"]: entry for entry in read_json(self.path, [])}

    def save(self, entries: dict[str, dict]) -> None:
        ordered = sorted(entries.values(), key=lambda entry: entry["updated"], reverse=True)
        write_json(self.path, ordered)

    def find_scored(self, reference: str) -> dict | None:
        """A job from saved search or match results, by id or by any of its URLs."""
        reference = reference.strip()
        for job in self.store.scored_jobs():
            urls = {job.get(key) for key in ("job_id", "url", "source_url", "application_url")}
            if reference in urls or reference.rstrip("/") in {str(url).rstrip("/") for url in urls if url}:
                return job
        return None

    def find_entry(self, entries: dict[str, dict], reference: str) -> dict | None:
        """By id or URL; failing that, by company, title or "<title> at <company>" when only one matches."""
        reference = reference.strip().rstrip("/")
        exact = next((entry for entry in entries.values()
                      if reference in (entry["id"], entry.get("job_id", ""), entry.get("url", "").rstrip("/"))), None)
        if exact or not reference:
            return exact
        wanted = reference.lower()
        named = [entry for entry in entries.values()
                 if wanted in (entry["company"].lower(), entry["title"].lower(),
                               f"{entry['title']} at {entry['company']}".lower())]
        if len(named) > 1:
            raise ValueError(f'{len(named)} tracked jobs match "{reference}"; use the job\'s URL or id.')
        return named[0] if named else None

    def sync_history(self, job_id: str, status: str) -> None:
        """Keep the status in the search history, so a later /job-search shows it."""
        history = read_json(self.store.history_path, None)
        if history and job_id in history.get("jobs", {}):
            history["jobs"][job_id]["status"] = status
            write_json(self.store.history_path, history)


def _valid_date(text: str | None) -> str:
    if not text:
        return today()
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ValueError(f'"{text}" is not a date; use YYYY-MM-DD') from error


def add(tracker: Tracker, arguments) -> int:
    entries = tracker.load()
    date = _valid_date(arguments.date)
    existing = tracker.find_entry(entries, arguments.job)
    if existing:
        print(f"Already tracked: {existing['title']} at {existing['company']}. Use update to change its status.",
              file=sys.stderr)
        return 1
    job = tracker.find_scored(arguments.job)
    if job is None and not (arguments.title and arguments.company):
        print("That job is not in your saved results. Give --title and --company to track it anyway.",
              file=sys.stderr)
        return 2
    url = (job or {}).get("source_url") or (job or {}).get("url") or (arguments.job if "://" in arguments.job else "")
    key = (job or {}).get("job_id") or "tracked:" + hashlib.sha1(
        (url or f"{arguments.title}|{arguments.company}").lower().encode()).hexdigest()[:12]
    entry = {
        "id": key,
        "job_id": (job or {}).get("job_id", ""),
        "title": arguments.title or (job or {}).get("title", ""),
        "company": arguments.company or (job or {}).get("company", ""),
        "location": (job or {}).get("location", ""),
        "url": url,
        "match_score": (job or {}).get("match_score"),
        "status": arguments.status,
        "applied": date if arguments.status != "saved" else "",
        "updated": date,
        "history": [{"status": arguments.status, "date": date, "note": arguments.note}],
    }
    entries[key] = entry
    tracker.save(entries)
    if entry["job_id"]:
        tracker.sync_history(entry["job_id"], arguments.status)
    print(f"Tracking {entry['title']} at {entry['company']}: {arguments.status} on {date}.")
    return 0


def update(tracker: Tracker, arguments) -> int:
    entries = tracker.load()
    entry = tracker.find_entry(entries, arguments.job)
    if entry is None:
        print("That job is not tracked yet. Use add first.", file=sys.stderr)
        return 1
    date = _valid_date(arguments.date)
    entry["history"].append({"status": arguments.status, "date": date, "note": arguments.note})
    entry["status"] = arguments.status
    entry["updated"] = max(entry["updated"], date)
    if arguments.status != "saved" and not entry.get("applied"):
        entry["applied"] = date
    tracker.save(entries)
    if entry.get("job_id"):
        tracker.sync_history(entry["job_id"], arguments.status)
    print(f"{entry['title']} at {entry['company']}: now {arguments.status} ({date}).")
    return 0


def remove(tracker: Tracker, arguments) -> int:
    entries = tracker.load()
    entry = tracker.find_entry(entries, arguments.job)
    if entry is None:
        print("That job is not tracked.", file=sys.stderr)
        return 1
    del entries[entry["id"]]
    tracker.save(entries)
    print(f"Stopped tracking {entry['title']} at {entry['company']}.")
    return 0


def needs_follow_up(entry: dict, on: str | None = None) -> bool:
    """Applied or interviewing, and no news for FOLLOW_UP_DAYS."""
    if entry["status"] not in ("applied", "interviewing"):
        return False
    quiet = dt.date.fromisoformat(on or today()) - dt.date.fromisoformat(entry["updated"])
    return quiet.days >= FOLLOW_UP_DAYS


def format_list(entries: list[dict]) -> str:
    rows = ["| Status | Role | Company | Applied | Last update | Match | Link |", "|---|---|---|---|---|---|---|"]
    for entry in entries:
        status = entry["status"] + (" (follow up?)" if needs_follow_up(entry) else "")
        score = "" if entry.get("match_score") is None else str(entry["match_score"])
        rows.append(f"| {status} | {entry['title']} | {entry['company']} | {entry.get('applied') or '-'} | "
                    f"{entry['updated']} | {score} | {entry.get('url') or '-'} |")
    counts = {status: sum(entry["status"] == status for entry in entries) for status in STATUSES}
    summary = ", ".join(f"{count} {status}" for status, count in counts.items() if count)
    return "\n".join(rows) + f"\n\n{len(entries)} tracked: {summary}."


def list_entries(tracker: Tracker, arguments) -> int:
    entries = list(tracker.load().values())
    if arguments.status:
        entries = [entry for entry in entries if entry["status"] == arguments.status]
    if not entries:
        print("No applications tracked yet." if not arguments.status else f"No applications marked {arguments.status}.")
        return 0
    # Open applications first, then closed ones; newest update first within each.
    entries.sort(key=lambda entry: entry["updated"], reverse=True)
    entries.sort(key=lambda entry: entry["status"] in CLOSED_STATUSES)
    print(format_list(entries))
    return 0


def run(arguments) -> int:
    tracker = Tracker(Path(arguments.data_dir) if arguments.data_dir else DATA_DIR)
    commands = {"list": list_entries, "add": add, "update": update, "remove": remove}
    try:
        return commands[arguments.command](tracker, arguments)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
