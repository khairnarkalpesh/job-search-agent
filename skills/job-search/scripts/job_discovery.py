"""Find which company boards to look at.

Companies are never hard-coded. Boards come from web search results or from
ones saved on earlier runs. Search queries are built only from job titles,
skills and a broad location, so personal details cannot reach a search engine.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from http_client import FetchError, HttpClient
from sources import JobBoard, board_from_url

SOURCE_SEARCH_SITES = {"greenhouse": ["job-boards.greenhouse.io", "boards.greenhouse.io"], "lever": ["jobs.lever.co"],
                       "ashby": ["jobs.ashbyhq.com"], "workable": ["apply.workable.com"],
                       "smartrecruiters": ["jobs.smartrecruiters.com"]}
_MAX_TITLES_IN_PLAN = 6
_MAX_SKILLS_IN_PLAN = 3
_MAX_PLACES = 2
_BLOCK_PAGE_MARKERS = ("anomaly-modal", "anomaly.js", "captcha", "unusual traffic")


class SearchBlocked(Exception):
    pass


def build_search_queries(profile: dict, sources: list[str], role_filter: str = "", location_filter: str = "",
                         remote_only: bool = False) -> list[dict]:
    """Queries to run with any web search tool, one per title or skill phrase and place.

    Each is {"query", "search_terms", "domains"}. query names every domain with site: ... OR,
    for search tools without a domain filter; search_terms is the same search without them,
    for tools that take domains as a filter instead. "Remote,India" is two places, so two
    searches, not the text "Remote,India".
    """
    titles = [role_filter] if role_filter else [role["title"] for role in profile.get("target_roles", [])[:_MAX_TITLES_IN_PLAN]]
    top_skills = [skill for skill in profile.get("skills", {}).get("programming_languages", [])
                  + profile.get("skills", {}).get("frameworks", [])][:_MAX_SKILLS_IN_PLAN]
    place_text = location_filter or ("Remote" if remote_only else _broad_location(profile))
    places = [place.strip() for place in place_text.split(",") if place.strip()][:_MAX_PLACES] or [""]

    domains = [domain for source in sources for domain in SOURCE_SEARCH_SITES.get(source, [])]
    if not domains or not titles:
        return []
    searches = [f'"{title}" {place}'.strip() for place in places for title in titles]
    searches += [f'"{skill}" {titles[0]} {places[0]}'.strip() for skill in top_skills]  # skill searches, first place only
    sites = " OR ".join(f"site:{domain}" for domain in domains)
    sites = f"({sites})" if len(domains) > 1 else sites
    return [{"query": f"{search} {sites}", "search_terms": search, "domains": domains} for search in searches]


def _broad_location(profile: dict) -> str:
    """Last part of the location only, normally the country."""
    location = profile.get("candidate", {}).get("location", "")
    return location.split(",")[-1].strip() if location else ""


def boards_from_urls(urls: list[str], allowed_sources: list[str]) -> list[JobBoard]:
    boards: dict[str, JobBoard] = {}
    for url in urls:
        board = board_from_url(url.strip())
        if board and board.source in allowed_sources:
            boards.setdefault(board.key(), board)
    return list(boards.values())


class DuckDuckGoSearch:
    """Best-effort search for command-line runs. A block page ends the search; it is not retried."""
    SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"

    def __init__(self, client: HttpClient):
        self.client = client

    def search(self, query: str) -> list[str]:
        try:
            page = self.client.get(self.SEARCH_URL.format(query=urllib.parse.quote_plus(query)))
        except FetchError as error:
            raise SearchBlocked(str(error)) from error
        return self.parse_results(page)

    @staticmethod
    def parse_results(page: str) -> list[str]:
        lowered = page.lower()
        if any(marker in lowered for marker in _BLOCK_PAGE_MARKERS):
            raise SearchBlocked("search engine returned a bot check")
        links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', page) or re.findall(r'href="([^"]*uddg=[^"]+)"', page)
        urls = []
        for link in links:
            link = html.unescape(link)
            target = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("uddg")
            urls.append(target[0] if target else link)
        return urls


def discover_board_urls(search_engine, queries: list[dict]) -> tuple[list[str], str]:
    """Run queries until done or blocked. Returns (urls, warning)."""
    urls: list[str] = []
    for item in queries:
        try:
            urls.extend(search_engine.search(item["query"]))
        except SearchBlocked as error:
            return urls, f"Web search unavailable ({error}); continuing with known boards."
    return urls, ""
