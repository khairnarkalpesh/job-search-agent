"""Greenhouse, through its public Job Board API (no key needed for reading)."""
from __future__ import annotations

import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
_HOST = re.compile(r"^(job-boards|boards)(\.eu)?\.greenhouse\.io$", re.IGNORECASE)
_NON_BOARD_PATHS = {"embed", "jobs", "api"}


def parse_jobs(payload: dict, slug: str) -> list[dict]:
    """Parser for the API payload, kept separate so a format change stays in one place."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Greenhouse payload has no jobs list")
    jobs = []
    for item in payload["jobs"]:
        if not isinstance(item, dict) or not item.get("title") or not item.get("absolute_url"):
            continue
        jobs.append(make_job(
            source="greenhouse",
            board=slug,
            job_id=str(item.get("id", "")),
            title=item["title"],
            company=item.get("company_name") or slug.replace("-", " ").title(),
            location=(item.get("location") or {}).get("name", ""),
            description=html_to_text(item.get("content", "")),
            url=item["absolute_url"],
            posted_at=item.get("first_published") or item.get("updated_at") or "",
        ))
    return jobs


class GreenhouseSource(Source):
    name = "greenhouse"
    label = "Greenhouse"

    def parse_url(self, url: str) -> JobBoard | None:
        parts = urllib.parse.urlsplit(url)
        if not _HOST.match(parts.netloc):
            return None
        segments = [segment for segment in parts.path.split("/") if segment]
        if segments[:2] == ["embed", "job_board"] or segments[:2] == ["embed", "job_app"]:
            slug = urllib.parse.parse_qs(parts.query).get("for", [""])[0]
            return JobBoard(self.name, slug) if slug else None
        if not segments or segments[0] in _NON_BOARD_PATHS:
            return None
        return JobBoard(self.name, segments[0])

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        url = API.format(slug=urllib.parse.quote(board.slug))
        payload = client.get_json(url)
        try:
            return parse_jobs(payload, board.slug)
        except ValueError as error:
            raise FetchError("malformed", url, str(error)) from error
