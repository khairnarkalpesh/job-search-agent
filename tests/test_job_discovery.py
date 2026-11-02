import pytest

from conftest import FIXTURES
from job_discovery import (DuckDuckGoSearch, SearchBlocked, boards_from_urls, build_search_queries, discover_board_urls)


def test_queries_use_several_titles_skills_and_both_sources(profile):
    queries = [item["query"] for item in build_search_queries(profile, ["greenhouse", "lever"])]
    assert len(queries) >= 6
    assert any("site:jobs.lever.co" in query for query in queries)
    assert any("site:job-boards.greenhouse.io" in query for query in queries)
    assert any('"Java Developer"' in query for query in queries)
    assert any('"Spring Boot"' in query for query in queries)


def test_queries_contain_no_personal_details(profile):
    queries = " ".join(item["query"] for item in build_search_queries(profile, ["greenhouse", "lever"])).lower()
    for private_value in ("asha", "testcandidate", "northwind", "contoso", "example.com", "98765", "pune"):
        assert private_value not in queries
    assert "india" in queries  # country level only


def test_only_requested_sources_are_searched(profile):
    queries = build_search_queries(profile, ["lever"])
    assert all(item["domains"] == ["jobs.lever.co"] for item in queries)
    assert all(" OR " not in item["query"] for item in queries)


def test_one_query_per_phrase_covers_every_company_board_site(profile):
    queries = build_search_queries(profile, ["greenhouse", "lever", "ashby", "workable", "smartrecruiters"])
    assert len(queries) <= 9  # one per title or skill phrase, not one per site
    for site in ("job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com", "jobs.smartrecruiters.com"):
        assert all(f"site:{site}" in item["query"] for item in queries)


def test_portals_and_websites_add_no_search_queries(profile):
    assert build_search_queries(profile, ["remotive", "generic"]) == []


def test_role_and_location_filters_shape_queries(profile):
    queries = build_search_queries(profile, ["lever"], role_filter="Java Developer", location_filter="Bangalore")
    assert all("Java Developer" in item["query"] and "Bangalore" in item["query"] for item in queries)


def test_boards_are_unique_and_limited_to_allowed_sources():
    urls = ["https://jobs.lever.co/acme/1", "https://jobs.lever.co/acme/2", "https://job-boards.greenhouse.io/other/jobs/1", "https://example.com/x"]
    assert [board.slug for board in boards_from_urls(urls, ["lever"])] == ["acme"]


def test_a_real_block_page_stops_the_search():
    page = (FIXTURES / "recorded_duckduckgo_block_page.html").read_text(encoding="utf-8")
    with pytest.raises(SearchBlocked):
        DuckDuckGoSearch.parse_results(page)


def test_result_links_are_decoded():
    page = '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Facme%2F1&amp;rut=x">Job</a>'
    assert DuckDuckGoSearch.parse_results(page) == ["https://jobs.lever.co/acme/1"]


def test_empty_search_results_are_fine():
    assert DuckDuckGoSearch.parse_results("<html>No results</html>") == []


class BlockedAfterFirstQuery:
    def __init__(self):
        self.calls = 0

    def search(self, query):
        self.calls += 1
        if self.calls > 1:
            raise SearchBlocked("bot check")
        return ["https://jobs.lever.co/acme/1"]


def test_block_stops_querying_and_keeps_earlier_results():
    search_engine = BlockedAfterFirstQuery()
    urls, warning = discover_board_urls(search_engine, [{"query": "a"}, {"query": "b"}, {"query": "c"}])
    assert urls == ["https://jobs.lever.co/acme/1"]
    assert search_engine.calls == 2  # never retried after the block
    assert "unavailable" in warning
