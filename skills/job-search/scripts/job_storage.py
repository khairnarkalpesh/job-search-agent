"""Everything written to disk: profile, results, search history, known boards and preferences."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from skill_taxonomy import PREFERENCES_FILE, today
from sources import JobBoard

STATUS_NEW = "new"
SEEN_NEW = "NEW JOB"
SEEN_BEFORE = "PREVIOUSLY SEEN"


UNREVIEWED_PROFILE = ("Warning: your profile is an unreviewed draft read by rules alone. Its skills and target roles "
                      "may be wrong, and so may every score. Review it first (/job-profile).")


def profile_warning(profile: dict) -> str:
    """A warning for a draft profile nobody has checked; empty once it is reviewed.

    Profiles saved before the flag existed carry no "reviewed" key and are not warned about.
    """
    return UNREVIEWED_PROFILE if profile.get("reviewed") is False else ""


def read_json(path: Path, default):
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary_path, path)


def load_preferences(path: Path = PREFERENCES_FILE) -> dict:
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("job_preferences", {}) or {}


def save_preferences(preferences: dict, path: Path = PREFERENCES_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"job_preferences": preferences}, sort_keys=False, allow_unicode=True), encoding="utf-8")


class JobStore:
    def __init__(self, data_dir: Path):
        self.profile_path = data_dir / "candidate_profile.json"
        self.results_path = data_dir / "job_results.json"
        self.history_path = data_dir / "search_history.json"
        self.boards_path = data_dir / "known_boards.json"
        self.matches_path = data_dir / "matched_jobs.json"

    def record_match(self, scored_job: dict) -> None:
        """Keep a job scored on its own with /job-match, so /job-gaps can count it too."""
        matches = {job["job_id"]: job for job in read_json(self.matches_path, [])}
        matches[scored_job["job_id"]] = {**scored_job, "date_matched": today()}
        write_json(self.matches_path, list(matches.values()))

    def scored_jobs(self) -> list[dict]:
        """Search results and individually matched jobs, each job once (the latest scoring wins)."""
        jobs: dict[str, dict] = {}
        for position, job in enumerate(read_json(self.results_path, []) + read_json(self.matches_path, [])):
            jobs[job.get("job_id") or f"unidentified:{position}"] = job
        return list(jobs.values())

    def load_profile(self) -> dict | None:
        return read_json(self.profile_path, None) or None

    def save_profile(self, profile: dict) -> None:
        write_json(self.profile_path, profile)

    def known_boards(self) -> list[JobBoard]:
        return [JobBoard(**entry) for entry in read_json(self.boards_path, [])]

    def add_boards(self, boards: list[JobBoard]) -> None:
        """Boards the user asked to watch, company website pages included."""
        merged = {board.key(): board for board in self.known_boards() + boards}
        write_json(self.boards_path, [board.to_dict() for board in sorted(merged.values(), key=JobBoard.key)])

    def remove_boards(self, keys: set[str]) -> list[JobBoard]:
        removed = [board for board in self.known_boards() if board.key() in keys]
        kept = [board for board in self.known_boards() if board.key() not in keys]
        write_json(self.boards_path, [board.to_dict() for board in kept])
        return removed

    def remember_boards(self, boards: list[JobBoard]) -> None:
        """Generic page URLs are one-offs, so only real boards are kept."""
        merged = {board.key(): board for board in self.known_boards()}
        merged.update({board.key(): board for board in boards if board.source != "generic"})
        write_json(self.boards_path, [board.to_dict() for board in sorted(merged.values(), key=JobBoard.key)])

    def record_results(self, scored_jobs: list[dict], run_summary: dict) -> None:
        """Label each job new or seen, then merge into results and history.

        A status set by the user survives later runs, and jobs missing from this
        run stay on file.
        """
        history = read_json(self.history_path, {"jobs": {}, "runs": []})
        results = {job["job_id"]: job for job in read_json(self.results_path, [])}
        date = today()

        for job in scored_jobs:
            job_id = job["job_id"]
            previous = history["jobs"].get(job_id)
            job["seen"] = SEEN_BEFORE if previous else SEEN_NEW
            job["status"] = (previous or {}).get("status", STATUS_NEW)
            job["date_found"] = (previous or {}).get("date_first_discovered", date)
            job["url"] = job["source_url"]
            job["previous_score"] = (previous or {}).get("score")
            history["jobs"][job_id] = {
                "job_id": job_id,
                "url": job["source_url"],
                "date_first_discovered": job["date_found"],
                "date_last_seen": date,
                "previous_score": job["previous_score"],
                "score": job["match_score"],
                "status": job["status"],
            }
            results[job_id] = job

        history["runs"].append({"date": date, **run_summary})
        write_json(self.results_path, sorted(results.values(), key=lambda job: job["match_score"], reverse=True))
        write_json(self.history_path, history)
