import json

import pytest

from conftest import FIXTURES
from http_client import FetchError
from normalize_jobs import enrich_job
from sources import JobBoard, board_from_url
from sources.greenhouse import GreenhouseSource, parse_jobs

RECORDED = json.loads((FIXTURES / "recorded_greenhouse_capco.json").read_text(encoding="utf-8"))


def test_recorded_response_is_parsed_into_complete_jobs():
    jobs = parse_jobs(RECORDED, "capco")
    assert len(jobs) == len(RECORDED["jobs"])
    for job, raw in zip(jobs, RECORDED["jobs"]):
        assert job["title"] == raw["title"]
        assert job["company"] == "Capco"
        assert job["location"] == " ".join(raw["location"]["name"].split())
        assert job["source_url"] == raw["absolute_url"]
        assert job["job_id"] == f"greenhouse:capco:{raw['id']}"


def test_description_has_no_markup_left():
    job = parse_jobs(RECORDED, "capco")[0]
    assert len(job["description"]) > 300
    assert "<" not in job["description"] and "&lt;" not in job["description"]


def test_enrichment_finds_requirements_and_technologies():
    job = enrich_job(parse_jobs(RECORDED, "capco")[0])
    assert job["requirements"]
    assert "Java" in job["technologies"]


@pytest.mark.parametrize("url,slug", [
    ("https://job-boards.greenhouse.io/capco/jobs/7780203", "capco"),
    ("https://boards.greenhouse.io/stripe", "stripe"),
    ("https://job-boards.eu.greenhouse.io/acme/jobs/1", "acme"),
    ("https://boards.greenhouse.io/embed/job_board?for=gitlab", "gitlab"),
    ("https://job-boards.greenhouse.io/yipitdata/jobs/8280705&gsessionid=abc", "yipitdata"),
])
def test_board_is_recognised_from_url(url, slug):
    assert board_from_url(url) == JobBoard("greenhouse", slug)


def test_unrelated_url_is_not_greenhouse():
    assert GreenhouseSource().parse_url("https://example.com/capco") is None


@pytest.mark.parametrize("payload", [{}, {"jobs": "none"}, [], "text"])
def test_unexpected_payload_is_rejected(payload):
    with pytest.raises(ValueError):
        parse_jobs(payload, "capco")


def test_entries_missing_core_fields_are_skipped():
    assert parse_jobs({"jobs": [{"title": "No URL"}, {"absolute_url": "https://x"}, "junk"]}, "capco") == []


def test_job_with_no_location_stays_empty():
    job = parse_jobs({"jobs": [{"title": "Engineer", "absolute_url": "https://x/1", "id": 1}]}, "capco")[0]
    assert job["location"] == ""
    assert job["remote"] is None


class ClientReturning:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url):
        return self.payload


def test_malformed_response_becomes_a_fetch_error():
    with pytest.raises(FetchError) as error:
        GreenhouseSource().fetch_board(JobBoard("greenhouse", "capco"), ClientReturning({"oops": 1}))
    assert error.value.kind == "malformed"
