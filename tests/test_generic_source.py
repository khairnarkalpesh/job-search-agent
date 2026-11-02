import json

import pytest

from conftest import RecordedClient
from http_client import FetchError
from sources import JobBoard
from sources.generic import MAX_JOB_LINKS, GenericSource, job_links, parse_page

URL = "https://careers.test-co.example/jobs/1"


def page_with(data) -> str:
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script></html>'


POSTING = {"@type": "JobPosting", "title": "Backend Engineer", "description": "<p>Java and <b>SQL</b></p>",
           "hiringOrganization": {"name": "Test Co"}, "employmentType": "FULL_TIME",
           "jobLocation": {"address": {"addressLocality": "Pune", "addressCountry": "India"}}}


def test_job_posting_data_is_extracted():
    job = parse_page(page_with(POSTING), URL)[0]
    assert (job["title"], job["company"], job["location"]) == ("Backend Engineer", "Test Co", "Pune, India")
    assert job["description"] == "Java and\nSQL" or "SQL" in job["description"]
    assert job["source_url"] == URL


def test_graph_wrapper_is_followed():
    assert len(parse_page(page_with({"@graph": [{"@type": "WebPage"}, POSTING]}), URL)) == 1


def test_telecommute_means_remote():
    job = parse_page(page_with({**POSTING, "jobLocationType": "TELECOMMUTE", "jobLocation": []}), URL)[0]
    assert job["remote"] is True and job["location"] == "Remote"


@pytest.mark.parametrize("markup", [
    "<html>No structured data</html>",
    '<script type="application/ld+json">{broken</script>',
    page_with({"@type": "Organization", "name": "Test Co"}),
    page_with({"@type": "JobPosting", "title": "No description"}),
])
def test_pages_without_usable_data_give_no_jobs(markup):
    assert parse_page(markup, URL) == []


def test_page_without_job_data_is_reported_not_invented():
    class ClientReturningPlainPage:
        def get(self, url, check_robots=False):
            return "<html>Hello</html>"

    with pytest.raises(FetchError) as error:
        GenericSource().fetch_board(JobBoard("generic", URL), ClientReturningPlainPage())
    assert error.value.kind == "malformed"


CAREERS = "https://www.test-co.example/careers"


def test_careers_page_powered_by_a_board_reads_that_board():
    page = ('<html><a href="https://jobs.lever.co/Onehouse">Open roles</a>'
            '<iframe src="https://boards.greenhouse.io/embed/job_board?for=capco&amp;b=x"></iframe></html>')
    jobs = GenericSource().fetch_board(JobBoard("generic", CAREERS), RecordedClient(pages={CAREERS: page}))
    assert {job["source"] for job in jobs} == {"lever", "greenhouse"}


def test_careers_page_follows_same_site_job_links():
    page = ('<a href="/careers/backend-engineer">Backend</a><a href="/careers">All</a>'
            '<a href="https://elsewhere.example/careers/x">Other site</a><a href="/about">About</a>')
    pages = {CAREERS: page, "https://www.test-co.example/careers/backend-engineer": page_with(POSTING)}
    client = RecordedClient(pages=pages)
    jobs = GenericSource().fetch_board(JobBoard("generic", CAREERS), client)
    assert [job["title"] for job in jobs] == ["Backend Engineer"]
    assert "https://elsewhere.example/careers/x" not in client.requested


def test_job_links_are_capped_and_unique():
    page = "".join(f'<a href="/jobs/{n}">x</a><a href="/jobs/{n}#apply">x</a>' for n in range(50))
    links = job_links(page, CAREERS)
    assert len(links) == MAX_JOB_LINKS and len(set(links)) == len(links)


def test_postings_on_one_page_get_distinct_ids():
    other = {**POSTING, "title": "Data Engineer"}
    jobs = parse_page(page_with([POSTING, other]), URL)
    assert len({job["job_id"] for job in jobs}) == 2
