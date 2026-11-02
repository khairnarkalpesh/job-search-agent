"""Company career websites.

A page is read in this order, and the first step that finds jobs wins:
1. schema.org JobPosting data on the page itself (the format Google Jobs reads);
2. a link to, or embed of, a supported applicant-tracking system, whose whole board
   is then read through its API;
3. up to MAX_JOB_LINKS job links on the same site, each checked for JobPosting data.
Every request honours robots.txt. Pages that load jobs only through JavaScript give
nothing here; Claude can still read them and score a job with /job-match.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse

from http_client import FetchError
from normalize_jobs import html_to_text, make_job

from .base import JobBoard, Source

MAX_JOB_LINKS = 20
MAX_LINKED_BOARDS = 3
_HREF = re.compile(r"""(?:href|src|data-url)=["']([^"'#]+)""", re.IGNORECASE)
_ATS_URL = re.compile(r"""https?://(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/[^\s"'<>]+"""
                      r"""|https?://jobs(?:\.eu)?\.lever\.co/[^\s"'<>]+"""
                      r"""|https?://jobs\.ashbyhq\.com/[^\s"'<>]+"""
                      r"""|https?://(?:apply\.workable\.com|[a-z0-9-]+\.workable\.com)/?[^\s"'<>]*"""
                      r"""|https?://(?:jobs|careers)\.smartrecruiters\.com/[^\s"'<>]+""", re.IGNORECASE)
_JOB_PATH = re.compile(r"/(jobs?|careers?|positions?|openings?|vacanc(y|ies)|roles?|opportunit(y|ies))(/|-|$)",
                       re.IGNORECASE)

_JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)


def _postings(node):
    if isinstance(node, list):
        for item in node:
            yield from _postings(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            yield node
        if "@graph" in node:
            yield from _postings(node["@graph"])


def _location(posting: dict) -> str:
    places = posting.get("jobLocation") or []
    names = []
    for place in places if isinstance(places, list) else [places]:
        address = place.get("address", {}) if isinstance(place, dict) else {}
        if isinstance(address, str):
            names.append(address)
        elif isinstance(address, dict):
            country = address.get("addressCountry")
            country = country.get("name", "") if isinstance(country, dict) else country
            address_parts = [address.get("addressLocality"), address.get("addressRegion"), country]
            names.append(", ".join(str(part) for part in address_parts if part))
    return "; ".join(name for name in names if name)


def parse_page(markup: str, url: str) -> list[dict]:
    """Extract jobs from a page's JSON-LD. Pages without it return an empty list."""
    jobs = []
    for block in _JSON_LD.findall(markup):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for posting in _postings(data):
            if not posting.get("title") or not posting.get("description"):
                continue
            company = posting.get("hiringOrganization")
            company = company.get("name", "") if isinstance(company, dict) else str(company or "")
            remote = True if posting.get("jobLocationType") == "TELECOMMUTE" else None
            employment = posting.get("employmentType", "")
            jobs.append(make_job(
                source="generic",
                board=urllib.parse.urlsplit(url).netloc,
                job_id=hashlib.sha1(f"{url}|{posting['title']}".encode()).hexdigest()[:16],
                title=posting["title"],
                company=company or urllib.parse.urlsplit(url).netloc,
                location=_location(posting) or ("Remote" if remote else ""),
                description=html_to_text(posting["description"]),
                url=url,
                employment_type=str(employment).lower().replace("-", "_"),
                remote=remote,
                posted_at=str(posting.get("datePosted", "")),
            ))
    return jobs


def linked_boards(markup: str) -> list[JobBoard]:
    """Applicant-tracking boards a careers page links to or embeds."""
    from . import ATS_SOURCES, board_from_url  # imported here: the package imports this module
    boards: dict[str, JobBoard] = {}
    for url in _ATS_URL.findall(html.unescape(markup)):
        board = board_from_url(url)
        if board and board.source in ATS_SOURCES:
            boards.setdefault(board.key(), board)
    return list(boards.values())[:MAX_LINKED_BOARDS]


def job_links(markup: str, page_url: str) -> list[str]:
    """Links on the same site whose path looks like a single job."""
    site = urllib.parse.urlsplit(page_url).netloc.lower()
    links = []
    for href in _HREF.findall(markup):
        url = urllib.parse.urljoin(page_url, html.unescape(href.strip()))
        parts = urllib.parse.urlsplit(url)
        same_site = parts.scheme in ("http", "https") and parts.netloc.lower() == site and url != page_url
        # One level below a jobs path, such as /careers/backend-engineer, not /careers itself.
        if same_site and _JOB_PATH.search(parts.path) and parts.path.rstrip("/").count("/") >= 2:
            links.append(url.split("#")[0])
    return list(dict.fromkeys(links))[:MAX_JOB_LINKS]


class GenericSource(Source):
    name = "generic"
    label = "Company website"
    kind = "website"

    def parse_url(self, url: str) -> JobBoard | None:
        return JobBoard(self.name, url) if url.lower().startswith(("http://", "https://")) else None

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        from . import SOURCES
        markup = client.get(board.slug, check_robots=True)
        jobs = parse_page(markup, board.slug)
        if jobs:
            return jobs
        for linked in linked_boards(markup):
            try:
                jobs.extend(SOURCES[linked.source].fetch_board(linked, client))
            except FetchError:
                continue
        if jobs:
            return jobs
        for link in job_links(markup, board.slug):
            try:
                jobs.extend(parse_page(client.get(link, check_robots=True), link))
            except FetchError:
                continue
        if not jobs:
            raise FetchError("malformed", board.slug, "no machine-readable job listings on this page")
        return jobs
