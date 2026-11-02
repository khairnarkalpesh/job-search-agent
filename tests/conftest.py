"""Test setup. Nothing here is reachable from the application.

tests/fixtures/ holds real API responses (recorded_*), a real block page, and a
labelled synthetic resume. Jobs built with build_job exist only as unit-test
input for scoring rules, and every one uses the placeholder company "Test Co".
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent / "skills" / "job-search"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

# Keep test runs away from the user's real data. Live tests read the real folder.
REAL_USER_HOME = Path(os.environ.get("JOB_SEARCH_AGENT_HOME") or Path.home() / ".job-search-agent")
os.environ["JOB_SEARCH_AGENT_HOME"] = tempfile.mkdtemp(prefix="job-search-agent-tests-")

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REFERENCE_DATE = dt.date(2026, 11, 1)


@pytest.fixture
def profile():
    from resume_parser import build_profile
    return build_profile((FIXTURES / "synthetic_resume.md").read_text(encoding="utf-8"), REFERENCE_DATE)


def build_job(title="Backend Engineer", location="Pune, India", description=None, **fields):
    from normalize_jobs import enrich_job, make_job
    if description is None:
        description = ("Requirements\n- 3+ years of experience with Java and Spring Boot\n- REST APIs and PostgreSQL\n"
                       "- Docker and AWS\nNice to have\n- Kubernetes\n" + "We build payment systems. " * 15)
    return enrich_job(make_job(source=fields.pop("source", "lever"), board="test-co", job_id=fields.pop("job_id", "1"),
                               title=title, company=fields.pop("company", "Test Co"), location=location,
                               description=description, url=fields.pop("url", "https://jobs.lever.co/test-co/1"), **fields))


def recorded(name):
    import json
    return json.loads((FIXTURES / f"recorded_{name}.json").read_text(encoding="utf-8"))


# Real responses, keyed by a piece of the URL that requests them.
RECORDED_ROUTES = [
    ("boards-api.greenhouse.io", "greenhouse_capco", {"jobs": []}),
    ("api.lever.co", "lever_onehouse", []),
    ("api.ashbyhq.com", "ashby_ashby", {"jobs": []}),
    ("apply.workable.com", "workable_huggingface", {"jobs": []}),
    ("smartrecruiters.com/v1/companies/BoschGroup/postings/", "smartrecruiters_boschgroup_detail", {}),
    ("api.smartrecruiters.com", "smartrecruiters_boschgroup", {"content": [], "totalFound": 0}),
    ("remotive.com", "remotive_backend", {"jobs": []}),
    ("remoteok.com", "remoteok_backend", []),
    ("himalayas.app", "himalayas_backend", {"jobs": []}),
    ("arbeitnow.com", "arbeitnow_latest", {"data": []}),
]


class RecordedClient:
    """Serves recorded real responses. A URL containing a key of `failures` fails with
    that kind; `pages` maps URLs to HTML for the website reader."""

    def __init__(self, failures=None, empty=False, pages=None):
        from http_client import FetchError
        self.FetchError = FetchError
        self.failures = failures or {}
        self.empty = empty
        self.pages = pages or {}
        self.requested = []

    def get_json(self, url, cache_hours=0):
        self.requested.append(url)
        for key, kind in self.failures.items():
            if key in url:
                raise self.FetchError(kind, url)
        for marker, name, empty_payload in RECORDED_ROUTES:
            if marker in url:
                return empty_payload if self.empty else recorded(name)
        raise self.FetchError("not_found", url)

    def get(self, url, check_robots=False):
        self.requested.append(url)
        if url in self.pages:
            return self.pages[url]
        raise self.FetchError("blocked", url, "bot check")
