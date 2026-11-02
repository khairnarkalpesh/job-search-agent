"""Ashby, Workable, SmartRecruiters and the job portals, parsed from recorded real responses."""
import pytest

from conftest import RecordedClient, recorded
from http_client import FetchError
from sources import ATS_SOURCES, PORTAL_SOURCES, SOURCES, JobBoard, board_from_url
from sources import ashby, portals, smartrecruiters, workable


def assert_usable(jobs):
    assert jobs
    for job in jobs:
        assert job["title"] and job["source_url"].startswith("https://")
        assert job["job_id"].count(":") >= 2


def test_ashby_listings_are_parsed():
    jobs = ashby.parse_jobs(recorded("ashby_ashby"), "ashby")
    assert_usable(jobs)
    assert all(job["company"] == "Ashby" and len(job["description"]) > 300 for job in jobs)


def test_workable_listings_are_parsed():
    jobs = workable.parse_jobs(recorded("workable_huggingface"), "huggingface")
    assert_usable(jobs)
    assert all(job["company"] == "Hugging Face" for job in jobs)


def test_smartrecruiters_listing_has_no_text_until_completed():
    jobs = smartrecruiters.parse_listing(recorded("smartrecruiters_boschgroup"), "BoschGroup")
    assert_usable(jobs)
    assert all(job["description"] == "" for job in jobs)
    completed = SOURCES["smartrecruiters"].complete_job(jobs[0], RecordedClient())
    assert len(completed["description"]) > 300
    assert completed["source_url"].startswith("https://jobs.smartrecruiters.com/BoschGroup/")


def test_smartrecruiters_detail_failure_keeps_the_job():
    job = smartrecruiters.parse_listing(recorded("smartrecruiters_boschgroup"), "BoschGroup")[0]
    assert SOURCES["smartrecruiters"].complete_job(job, RecordedClient({"/postings/": "network"})) == job


def test_smartrecruiters_unknown_company_is_not_found():
    with pytest.raises(FetchError) as error:
        SOURCES["smartrecruiters"].fetch_board(JobBoard("smartrecruiters", "Nobody"), RecordedClient(empty=True))
    assert error.value.kind == "not_found"


@pytest.mark.parametrize("name, fixture", [
    ("remotive", "remotive_backend"), ("remoteok", "remoteok_backend"),
    ("himalayas", "himalayas_backend"), ("arbeitnow", "arbeitnow_latest"),
])
def test_portal_listings_are_parsed(name, fixture):
    jobs = SOURCES[name].parse_jobs(recorded(fixture), "backend")
    assert_usable(jobs)
    assert all(job["source"] == name and job["company"] for job in jobs)


def test_remote_ok_terms_notice_is_not_a_job():
    payload = recorded("remoteok_backend")
    assert "legal" in payload[0]
    assert len(SOURCES["remoteok"].parse_jobs(payload, "backend")) == len(payload) - 1


def test_remote_only_portals_mark_jobs_remote():
    for name, fixture in (("remotive", "remotive_backend"), ("remoteok", "remoteok_backend"), ("himalayas", "himalayas_backend")):
        assert all(job["remote"] is True for job in SOURCES[name].parse_jobs(recorded(fixture), "x"))


@pytest.mark.parametrize("name", ["ashby", "workable", "remotive", "himalayas"])
def test_malformed_payload_is_reported(name):
    class Garbage:
        def get_json(self, url, cache_hours=0):
            return {"unexpected": True}
    board = JobBoard(name, "acme")
    with pytest.raises(FetchError) as error:
        SOURCES[name].fetch_board(board, Garbage())
    assert error.value.kind == "malformed"


def test_portals_search_target_roles_with_a_limit():
    boards = SOURCES["remotive"].boards_for(["Backend Engineer", "Java Developer", "Backend Engineer", "SRE", "Data Engineer"])
    assert [board.slug for board in boards] == ["Backend Engineer", "Java Developer", "SRE"]
    assert [board.slug for board in SOURCES["arbeitnow"].boards_for(["Backend Engineer"])] == ["latest"]
    assert [board.slug for board in SOURCES["remoteok"].boards_for(["Backend Engineer", "Java Developer"])] == ["Backend", "Java"]


def test_company_boards_and_websites_make_no_portal_searches():
    for name in ATS_SOURCES + ["generic"]:
        assert SOURCES[name].boards_for(["Backend Engineer"]) == []


def test_portal_requests_are_cached():
    client = RecordedClient()
    calls = []
    client.get_json = lambda url, cache_hours=0: calls.append(cache_hours) or recorded("remotive_backend")
    SOURCES["remotive"].fetch_board(JobBoard("remotive", "backend"), client)
    assert calls == [portals.PORTAL_CACHE_HOURS]


@pytest.mark.parametrize("url, expected", [
    ("https://jobs.ashbyhq.com/ashby/7458d4e9", ("ashby", "ashby")),
    ("https://jobs.ashbyhq.com/Acme%20Co", ("ashby", "Acme Co")),
    ("https://apply.workable.com/huggingface/j/81B46579FE/", ("workable", "huggingface")),
    ("https://acme.workable.com/jobs/123", ("workable", "acme")),
    ("https://jobs.smartrecruiters.com/BoschGroup/744000159066799-engineer", ("smartrecruiters", "BoschGroup")),
    ("https://careers.smartrecruiters.com/Visa", ("smartrecruiters", "Visa")),
])
def test_company_board_urls_are_recognised(url, expected):
    board = board_from_url(url)
    assert (board.source, board.slug) == expected


@pytest.mark.parametrize("url", ["https://apply.workable.com/j/81B46579FE", "https://www.workable.com/pricing"])
def test_workable_links_without_an_account_fall_back_to_the_website_reader(url):
    assert board_from_url(url).source == "generic"


def test_portal_urls_are_not_company_boards():
    assert board_from_url("https://remotive.com/remote-jobs/software-development/x-1").source == "generic"
    assert set(PORTAL_SOURCES) == {"remotive", "remoteok", "himalayas", "arbeitnow"}
