"""Lever, through its public Postings API (no key needed for reading)."""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source, company_from_slug

API = {"": "https://api.lever.co/v0/postings/{slug}?mode=json",
       "eu": "https://api.eu.lever.co/v0/postings/{slug}?mode=json"}
_HOST = re.compile(r"^jobs(\.eu)?\.lever\.co$", re.IGNORECASE)
_COMMITMENT = {"full-time": "full_time", "full time": "full_time", "part-time": "part_time",
               "part time": "part_time", "contract": "contract", "intern": "internship",
               "internship": "internship"}


def _description(item: dict) -> str:
    # Lever keeps the requirement lists apart from the body. Each list heading is
    # restored so the section splitter treats it like any other posting.
    sections = [html_to_text(item.get("description", "")) or item.get("descriptionPlain", "")]
    for block in item.get("lists") or []:
        heading = html_to_text(block.get("text", ""))
        body = html_to_text(f"<ul>{block.get('content', '')}</ul>")
        sections.append(f"{heading}\n{body}")
    sections.append(html_to_text(item.get("additional", "")) or item.get("additionalPlain", ""))
    return "\n".join(s for s in sections if s)


def _salary(item: dict) -> str:
    salary = item.get("salaryRange") or {}
    if salary.get("min") and salary.get("max"):
        interval = str(salary.get("interval", "")).replace("-", " ")
        return f"{salary.get('currency', '')} {salary['min']:,}-{salary['max']:,} {interval}".strip()
    return ""


def parse_jobs(payload: list, slug: str) -> list[dict]:
    """Parser for the API payload, kept separate so a format change stays in one place."""
    if not isinstance(payload, list):
        raise ValueError("Lever payload is not a list")
    jobs = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("text") or not item.get("hostedUrl"):
            continue
        categories = item.get("categories") or {}
        created = item.get("createdAt")
        commitment = str(categories.get("commitment", "")).strip().lower()
        jobs.append(make_job(
            source="lever",
            board=slug,
            job_id=str(item.get("id", "")),
            title=item["text"],
            company=company_from_slug(slug),  # the API has no company name
            location=categories.get("location") or ", ".join(categories.get("allLocations") or []),
            description=_description(item),
            url=item["hostedUrl"],
            application_url=item.get("applyUrl", ""),
            employment_type=_COMMITMENT.get(commitment, commitment),
            salary=_salary(item),
            workplace_type=item.get("workplaceType") or "",
            posted_at=dt.datetime.fromtimestamp(created / 1000, dt.UTC).date().isoformat()
            if isinstance(created, (int, float)) else "",
        ))
    return jobs


class LeverSource(Source):
    name = "lever"
    label = "Lever"

    def parse_url(self, url: str) -> JobBoard | None:
        parts = urllib.parse.urlsplit(url)
        host = _HOST.match(parts.netloc)
        if not host:
            return None
        segments = [segment for segment in parts.path.split("/") if segment]
        if not segments:
            return None
        return JobBoard(self.name, segments[0], "eu" if host.group(1) else "")

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        url = API[board.region].format(slug=urllib.parse.quote(board.slug))
        payload = client.get_json(url)
        try:
            return parse_jobs(payload, board.slug)
        except ValueError as error:
            raise FetchError("malformed", url, str(error)) from error
