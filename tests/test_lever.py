import json

import pytest

from conftest import FIXTURES
from http_client import FetchError
from normalize_jobs import enrich_job
from sources import JobBoard, board_from_url
from sources.lever import LeverSource, parse_jobs

RECORDED = json.loads((FIXTURES / "recorded_lever_onehouse.json").read_text(encoding="utf-8"))


def test_recorded_response_is_parsed_into_complete_jobs():
    jobs = parse_jobs(RECORDED, "Onehouse")
    assert len(jobs) == len(RECORDED)
    for job, raw in zip(jobs, RECORDED):
        assert job["title"] == raw["text"]
        assert job["source_url"] == raw["hostedUrl"]
        assert job["application_url"] == raw["applyUrl"]
        assert job["location"]
        assert len(job["description"]) > 300


def test_requirement_lists_reach_the_section_splitter():
    job = enrich_job(parse_jobs(RECORDED, "Onehouse")[0])
    assert job["requirements"]
    assert job["technologies"]


def test_workplace_type_sets_remote():
    item = {"text": "Engineer", "hostedUrl": "https://x/1", "workplaceType": "remote", "categories": {"location": "India"}}
    assert parse_jobs([item], "acme")[0]["remote"] is True
    item["workplaceType"] = "hybrid"
    assert parse_jobs([item], "acme")[0]["remote"] is False


def test_listed_salary_range_is_kept():
    item = {"text": "Engineer", "hostedUrl": "https://x/1",
            "salaryRange": {"min": 90000, "max": 120000, "currency": "USD", "interval": "per-year-salary"}}
    assert parse_jobs([item], "acme")[0]["salary"].startswith("USD 90,000-120,000")


def test_company_name_drops_slug_suffix():
    assert parse_jobs([{"text": "Engineer", "hostedUrl": "https://x/1"}], "brillio-2")[0]["company"] == "Brillio"


@pytest.mark.parametrize("url,board", [
    ("https://jobs.lever.co/Onehouse/2e0958a7", JobBoard("lever", "Onehouse")),
    ("https://jobs.lever.co/spotify", JobBoard("lever", "spotify")),
    ("https://jobs.eu.lever.co/acme/123", JobBoard("lever", "acme", "eu")),
])
def test_board_is_recognised_from_url(url, board):
    assert board_from_url(url) == board


@pytest.mark.parametrize("payload", [{}, "text", None])
def test_unexpected_payload_is_rejected(payload):
    with pytest.raises(ValueError):
        parse_jobs(payload, "acme")


def test_entries_missing_core_fields_are_skipped():
    assert parse_jobs([{"text": "No URL"}, {"hostedUrl": "https://x"}, 7], "acme") == []


def test_malformed_response_becomes_a_fetch_error():
    class ClientReturningAnError:
        def get_json(self, url):
            return {"ok": False, "error": "Document not found"}

    with pytest.raises(FetchError) as error:
        LeverSource().fetch_board(JobBoard("lever", "acme"), ClientReturningAnError())
    assert error.value.kind == "malformed"
