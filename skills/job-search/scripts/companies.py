#!/usr/bin/env python
"""The companies every search checks.

    python scripts/companies.py list
    python scripts/companies.py add https://careers.acme.com  lever:globex  https://jobs.ashbyhq.com/initech
    python scripts/companies.py remove lever:globex

A careers website is checked first. If it is powered by a supported applicant-tracking
system, that board is saved instead, because its API gives complete listings.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from http_client import FetchError, HttpClient
from job_storage import JobStore
from skill_taxonomy import DATA_DIR, USER_HOME
from sources import SOURCES, JobBoard, board_from_url
from sources.generic import linked_boards


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List, add or remove the companies searched on every run.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Show saved companies")
    add = commands.add_parser("add", help="Add companies by careers URL, job URL or source:slug")
    add.add_argument("targets", nargs="+")
    add.add_argument("--no-check", action="store_true", help="Save without fetching to confirm")
    remove = commands.add_parser("remove", help="Remove companies by source:slug or URL")
    remove.add_argument("targets", nargs="+")
    parser.add_argument("--data-dir", help="Where saved data lives (default: your data folder)")
    return parser.parse_args(argv)


def to_board(target: str) -> JobBoard | None:
    if target.lower().startswith(("http://", "https://")):
        return board_from_url(target)
    source, _, slug = target.partition(":")
    return JobBoard(source, slug) if source in SOURCES and SOURCES[source].kind != "portal" and slug else None


def resolve_website(board: JobBoard, client) -> list[JobBoard]:
    """A careers page that links to a supported board becomes that board."""
    if board.source != "generic":
        return [board]
    return linked_boards(client.get(board.slug, check_robots=True)) or [board]


def describe(board: JobBoard) -> str:
    return f"{SOURCES[board.source].label:<16} {board.source}:{board.slug}" if board.source in SOURCES else board.key()


def failure_advice(error: FetchError, board: JobBoard) -> str:
    """A blocked network is not a wrong board name, so the advice differs."""
    if error.kind in ("network", "blocked"):
        return ("The site could not be reached, so the board name was not checked. "
                "To save it now and let the next search check it, add it again with --no-check.")
    if board.source == "generic":
        return "This page has no machine-readable listings; use /job-match on single jobs instead."
    return "No board by that name was found. Check the company's board name."


def add(targets: list[str], store: JobStore, client, check: bool) -> int:
    failures = 0
    for target in targets:
        board = to_board(target)
        if board is None:
            print(f"✗ {target}: not a URL or source:slug (sources: {', '.join(n for n, s in SOURCES.items() if s.kind != 'portal')})")
            failures += 1
            continue
        try:
            boards = resolve_website(board, client) if check else [board]
            for found in boards:
                count = len(SOURCES[found.source].fetch_board(found, client)) if check else None
                store.add_boards([found])
                print(f"✓ {describe(found)}" + (f"  ({count} open listings)" if count is not None else ""))
        except FetchError as error:
            print(f"✗ {target}: {error.kind}. {failure_advice(error, board)}")
            failures += 1
    return 1 if failures == len(targets) else 0


def run(arguments, client=None) -> int:
    store = JobStore(Path(arguments.data_dir) if arguments.data_dir else DATA_DIR)
    if arguments.command == "list":
        boards = store.known_boards()
        print("\n".join(describe(board) for board in boards) if boards else "No saved companies yet.")
        return 0
    if arguments.command == "add":
        return add(arguments.targets, store, client or HttpClient(cache_dir=USER_HOME / "cache"), not arguments.no_check)
    keys = {board.key() for board in map(to_board, arguments.targets) if board}
    removed = store.remove_boards(keys)
    for board in removed:
        print(f"Removed {describe(board)}")
    if not removed:
        print("None of those are saved. Run: companies.py list")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
