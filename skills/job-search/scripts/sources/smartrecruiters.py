"""SmartRecruiters, through its public Posting API (no key needed for reading).

The listing endpoint has no job text, so each posting that passes the title filter is
fetched once more in complete_job.
"""
from __future__ import annotations

import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source

LIST_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}"
DETAIL_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}"
_HOST = re.compile(r"^(jobs|careers)\.smartrecruiters\.com$", re.IGNORECASE)
_MAX_PAGES = 10
_EMPLOYMENT = {"permanent": "full_time", "full_time": "full_time", "part_time": "part_time",
               "contract": "contract", "temporary": "temporary", "internship": "internship"}
_SECTION_ORDER = ("jobDescription", "qualifications", "additionalInformation", "companyDescription")


def _location(location: dict) -> str:
    if location.get("remote") and not location.get("city"):
        return "Remote"
    parts = [location.get("city"), location.get("region"), str(location.get("country") or "").upper()]
    return ", ".join(part for part in parts if part)


def parse_listing(payload: dict, slug: str) -> list[dict]:
    """Jobs from one page of the listing endpoint, without descriptions."""
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise ValueError("SmartRecruiters payload has no content list")
    jobs = []
    for item in payload["content"]:
        if not isinstance(item, dict) or not item.get("name") or not item.get("id"):
            continue
        location = item.get("location") or {}
        employment = (item.get("typeOfEmployment") or {}).get("id", "")
        jobs.append(make_job(
            source="smartrecruiters",
            board=slug,
            job_id=str(item["id"]),
            title=item["name"],
            company=(item.get("company") or {}).get("name") or slug,
            location=_location(location),
            description="",
            url=f"https://jobs.smartrecruiters.com/{urllib.parse.quote(slug)}/{item['id']}",
            employment_type=_EMPLOYMENT.get(employment, ""),
            remote=True if location.get("remote") else None,
            workplace_type="hybrid" if location.get("hybrid") else "",
            posted_at=str(item.get("releasedDate") or "")[:10],
        ))
    return jobs


def parse_detail(payload: dict) -> dict:
    """Description and real URLs from the posting detail endpoint."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobAd"), dict):
        raise ValueError("SmartRecruiters posting has no job ad")
    sections = payload["jobAd"].get("sections") or {}
    texts = []
    for key in _SECTION_ORDER:
        section = sections.get(key) or {}
        body = html_to_text(section.get("text", ""))
        if body:
            texts.append(f"{section.get('title') or key}\n{body}")
    return {"description": "\n".join(texts), "postingUrl": payload.get("postingUrl", ""),
            "applyUrl": payload.get("applyUrl", "")}


class SmartRecruitersSource(Source):
    name = "smartrecruiters"
    label = "SmartRecruiters"

    def parse_url(self, url: str) -> JobBoard | None:
        parts = urllib.parse.urlsplit(url)
        if not _HOST.match(parts.netloc):
            return None
        segments = [segment for segment in parts.path.split("/") if segment]
        return JobBoard(self.name, segments[0]) if segments else None

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        jobs: list[dict] = []
        for page in range(_MAX_PAGES):
            url = LIST_API.format(slug=urllib.parse.quote(board.slug), offset=page * 100)
            payload = client.get_json(url)
            try:
                page_jobs = parse_listing(payload, board.slug)
            except ValueError as error:
                raise FetchError("malformed", url, str(error)) from error
            jobs.extend(page_jobs)
            if len(page_jobs) < 100 or len(jobs) >= int(payload.get("totalFound") or 0):
                break
        if not jobs:
            # An unknown company returns an empty list, not a 404.
            raise FetchError("not_found", LIST_API.format(slug=board.slug, offset=0), "no postings")
        return jobs

    def complete_job(self, job: dict, client) -> dict:
        if job["description"]:
            return job
        job_id = job["job_id"].rsplit(":", 1)[-1]
        url = DETAIL_API.format(slug=urllib.parse.quote(job["board"]), job_id=urllib.parse.quote(job_id))
        try:
            detail = parse_detail(client.get_json(url))
        except (FetchError, ValueError):
            return job  # scored as unreliable rather than dropped
        return {**job, "description": detail["description"],
                "source_url": detail["postingUrl"] or job["source_url"],
                "application_url": detail["applyUrl"] or detail["postingUrl"] or job["application_url"]}
