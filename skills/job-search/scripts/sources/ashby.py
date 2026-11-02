"""Ashby, through its public Job Posting API (no key needed for reading)."""
from __future__ import annotations

import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source, company_from_slug

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
_HOST = re.compile(r"^jobs\.ashbyhq\.com$", re.IGNORECASE)
_EMPLOYMENT = {"FullTime": "full_time", "PartTime": "part_time", "Contract": "contract",
               "Intern": "internship", "Temporary": "temporary"}


def _location(item: dict) -> str:
    places = [item.get("location") or ""]
    places += [place.get("location", "") for place in item.get("secondaryLocations") or [] if isinstance(place, dict)]
    return "; ".join(dict.fromkeys(place for place in places if place))


def parse_jobs(payload: dict, slug: str) -> list[dict]:
    """Parser for the API payload, kept separate so a format change stays in one place."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Ashby payload has no jobs list")
    jobs = []
    for item in payload["jobs"]:
        if not isinstance(item, dict) or not item.get("title") or not item.get("jobUrl"):
            continue
        if item.get("isListed") is False:
            continue
        compensation = item.get("compensation") or {}
        workplace = str(item.get("workplaceType") or "")
        jobs.append(make_job(
            source="ashby",
            board=slug,
            job_id=str(item.get("id", "")),
            title=item["title"],
            company=company_from_slug(slug),
            location=_location(item),
            description=html_to_text(item.get("descriptionHtml", "")) or item.get("descriptionPlain", ""),
            url=item["jobUrl"],
            application_url=item.get("applyUrl", ""),
            employment_type=_EMPLOYMENT.get(item.get("employmentType", ""), ""),
            salary=compensation.get("compensationTierSummary") or "",
            remote=True if item.get("isRemote") else None,
            workplace_type=workplace.lower(),
            posted_at=str(item.get("publishedAt") or "")[:10],
        ))
    return jobs


class AshbySource(Source):
    name = "ashby"
    label = "Ashby"

    def parse_url(self, url: str) -> JobBoard | None:
        parts = urllib.parse.urlsplit(url)
        if not _HOST.match(parts.netloc):
            return None
        segments = [segment for segment in parts.path.split("/") if segment]
        return JobBoard(self.name, urllib.parse.unquote(segments[0])) if segments else None

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        url = API.format(slug=urllib.parse.quote(board.slug))
        payload = client.get_json(url)
        try:
            return parse_jobs(payload, board.slug)
        except ValueError as error:
            raise FetchError("malformed", url, str(error)) from error
