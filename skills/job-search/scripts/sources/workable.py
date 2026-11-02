"""Workable, through the public jobs widget feed (no key needed for reading)."""
from __future__ import annotations

import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source, company_from_slug

API = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
_APPLY_HOST = re.compile(r"^apply\.workable\.com$", re.IGNORECASE)
_SUBDOMAIN_HOST = re.compile(r"^([a-z0-9-]+)\.workable\.com$", re.IGNORECASE)
_NON_ACCOUNT_PATHS = {"j", "api", "careers"}
_NON_ACCOUNT_SUBDOMAINS = {"apply", "www", "help", "resources", "jobs"}
_EMPLOYMENT = {"full-time": "full_time", "part-time": "part_time", "contract": "contract",
               "temporary": "temporary", "internship": "internship"}


def _location(item: dict) -> str:
    places = []
    for place in item.get("locations") or [item]:
        if isinstance(place, dict):
            parts = [place.get("city"), place.get("region") or place.get("state"), place.get("country")]
            places.append(", ".join(part for part in parts if part))
    return "; ".join(dict.fromkeys(place for place in places if place))


def parse_jobs(payload: dict, slug: str) -> list[dict]:
    """Parser for the API payload, kept separate so a format change stays in one place."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Workable payload has no jobs list")
    company = payload.get("name") or company_from_slug(slug)
    jobs = []
    for item in payload["jobs"]:
        if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
            continue
        employment = str(item.get("employment_type") or "").strip().lower()
        jobs.append(make_job(
            source="workable",
            board=slug,
            job_id=str(item.get("shortcode", "")),
            title=item["title"],
            company=company,
            location=_location(item),
            description=html_to_text(item.get("description", "")),
            url=item["url"],
            application_url=item.get("application_url", ""),
            employment_type=_EMPLOYMENT.get(employment, employment.replace("-", "_")),
            remote=True if item.get("telecommuting") else None,
            posted_at=str(item.get("published_on") or ""),
        ))
    return jobs


class WorkableSource(Source):
    name = "workable"
    label = "Workable"

    def parse_url(self, url: str) -> JobBoard | None:
        parts = urllib.parse.urlsplit(url)
        segments = [segment for segment in parts.path.split("/") if segment]
        if _APPLY_HOST.match(parts.netloc):
            # apply.workable.com/j/CODE links carry no account name, so they cannot name a board.
            if not segments or segments[0] in _NON_ACCOUNT_PATHS:
                return None
            return JobBoard(self.name, segments[0])
        subdomain = _SUBDOMAIN_HOST.match(parts.netloc)
        if subdomain and subdomain.group(1).lower() not in _NON_ACCOUNT_SUBDOMAINS:
            return JobBoard(self.name, subdomain.group(1))
        return None

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        url = API.format(slug=urllib.parse.quote(board.slug))
        payload = client.get_json(url)
        try:
            return parse_jobs(payload, board.slug)
        except ValueError as error:
            raise FetchError("malformed", url, str(error)) from error
