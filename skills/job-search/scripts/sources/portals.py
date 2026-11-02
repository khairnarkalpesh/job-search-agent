"""Job portals with free public APIs. Each is searched by role title, not by company.

Their terms ask for two things, and the report honours both: every job links to its
page on the portal, and the portal is named as the source. Remotive also asks for no
more than four calls a day, which the client's response cache takes care of.

Sites without a public API (LinkedIn, Indeed, Naukri, Glassdoor) are not here on
purpose: their terms forbid automated access. Use /job-match with pasted text instead.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source

_MAX_SEARCHES = 3
PORTAL_CACHE_HOURS = 6
_EMPLOYMENT = {"full_time": "full_time", "full time": "full_time", "full-time": "full_time",
               "part_time": "part_time", "part time": "part_time", "contract": "contract",
               "freelance": "contract", "internship": "internship", "intern": "internship"}


def _employment(value) -> str:
    return _EMPLOYMENT.get(str(value or "").strip().lower(), "")


def _date_from_timestamp(value) -> str:
    try:
        return dt.datetime.fromtimestamp(int(value), dt.UTC).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _salary(low, high, currency="", period="") -> str:
    if not low or not high:
        return ""
    return f"{currency} {int(low):,}-{int(high):,} {period}".strip()


class PortalSource(Source):
    kind = "portal"
    host = ""
    searchable = True

    def parse_url(self, url: str) -> JobBoard | None:
        # A single portal URL is matched by /job-match through the generic page reader.
        return None

    def boards_for(self, search_terms: list[str]) -> list[JobBoard]:
        if not self.searchable:
            return [JobBoard(self.name, "latest")]
        terms = list(dict.fromkeys(term.strip() for term in search_terms if term.strip()))
        return [JobBoard(self.name, term) for term in terms[:_MAX_SEARCHES]]

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        url = self.search_url(board.slug)
        payload = client.get_json(url, cache_hours=PORTAL_CACHE_HOURS)
        try:
            return self.parse_jobs(payload, board.slug)
        except ValueError as error:
            raise FetchError("malformed", url, str(error)) from error

    def search_url(self, term: str) -> str:
        raise NotImplementedError

    def parse_jobs(self, payload, term: str) -> list[dict]:
        raise NotImplementedError


class RemotiveSource(PortalSource):
    name = "remotive"
    label = "Remotive"

    def search_url(self, term: str) -> str:
        return f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote_plus(term)}"

    def parse_jobs(self, payload, term: str) -> list[dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("Remotive payload has no jobs list")
        jobs = []
        for item in payload["jobs"]:
            if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
                continue
            jobs.append(make_job(
                source=self.name, board=self.name, job_id=str(item.get("id", "")),
                title=item["title"], company=item.get("company_name", ""),
                location=item.get("candidate_required_location") or "Remote",
                description=html_to_text(item.get("description", "")), url=item["url"],
                employment_type=_employment(item.get("job_type")), salary=item.get("salary") or "",
                remote=True, posted_at=str(item.get("publication_date") or "")[:10],
            ))
        return jobs


class RemoteOkSource(PortalSource):
    name = "remoteok"
    label = "Remote OK"

    def search_url(self, term: str) -> str:
        # Remote OK filters by tag, and its tags are single lower-case words.
        tag = re.sub(r"[^a-z0-9]+", "-", term.lower().split()[0] if term.split() else "").strip("-")
        return f"https://remoteok.com/api?tag={urllib.parse.quote(tag)}"

    def boards_for(self, search_terms: list[str]) -> list[JobBoard]:
        first_words = [term.split()[0] for term in search_terms if term.split()]
        return super().boards_for(first_words)

    def parse_jobs(self, payload, term: str) -> list[dict]:
        if not isinstance(payload, list):
            raise ValueError("Remote OK payload is not a list")
        jobs = []
        for item in payload:
            # The first entry is the terms notice, not a job.
            if not isinstance(item, dict) or not item.get("position") or not item.get("url"):
                continue
            jobs.append(make_job(
                source=self.name, board=self.name, job_id=str(item.get("id", "")),
                title=item["position"], company=item.get("company", ""),
                location=item.get("location") or "Remote",
                description=html_to_text(item.get("description", "")), url=item["url"],
                application_url=item.get("apply_url", ""),
                salary=_salary(item.get("salary_min"), item.get("salary_max"), "USD", "a year"),
                remote=True, posted_at=str(item.get("date") or "")[:10],
            ))
        return jobs


class HimalayasSource(PortalSource):
    name = "himalayas"
    label = "Himalayas"

    def search_url(self, term: str) -> str:
        return f"https://himalayas.app/jobs/api/search?q={urllib.parse.quote_plus(term)}"

    def parse_jobs(self, payload, term: str) -> list[dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("Himalayas payload has no jobs list")
        jobs = []
        for item in payload["jobs"]:
            url = item.get("applicationLink") or item.get("guid") if isinstance(item, dict) else ""
            if not url or not item.get("title"):
                continue
            restrictions = item.get("locationRestrictions") or []
            jobs.append(make_job(
                source=self.name, board=self.name, job_id=str(item.get("guid") or url),
                title=item["title"], company=item.get("companyName", ""),
                location="Remote" + (f" ({', '.join(restrictions)})" if restrictions else ""),
                description=html_to_text(item.get("description", "")) or item.get("excerpt", ""),
                url=item.get("guid") or url, application_url=url,
                employment_type=_employment(item.get("employmentType")),
                salary=_salary(item.get("minSalary"), item.get("maxSalary"), item.get("currency", ""),
                               item.get("salaryPeriod", "")),
                remote=True, posted_at=_date_from_timestamp(item.get("pubDate")),
            ))
        return jobs


class ArbeitnowSource(PortalSource):
    name = "arbeitnow"
    label = "Arbeitnow"
    searchable = False  # one feed of recent jobs, mostly in Germany and the EU

    def search_url(self, term: str) -> str:
        return "https://www.arbeitnow.com/api/job-board-api"

    def parse_jobs(self, payload, term: str) -> list[dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Arbeitnow payload has no data list")
        jobs = []
        for item in payload["data"]:
            if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
                continue
            types = [_employment(kind) for kind in item.get("job_types") or []]
            jobs.append(make_job(
                source=self.name, board=self.name, job_id=str(item.get("slug", "")),
                title=item["title"], company=item.get("company_name", ""),
                location=item.get("location", ""), description=html_to_text(item.get("description", "")),
                url=item["url"], employment_type=next((kind for kind in types if kind), ""),
                remote=True if item.get("remote") else None,
                posted_at=_date_from_timestamp(item.get("created_at")),
            ))
        return jobs
