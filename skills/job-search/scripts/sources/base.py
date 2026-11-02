"""The contract every job source implements."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class JobBoard:
    """One place to fetch from.

    slug is a board token for an applicant-tracking system, a search term for a job
    portal, or a full URL for a company website.
    """
    source: str
    slug: str
    region: str = ""

    def key(self) -> str:
        return f"{self.source}:{self.region}:{self.slug}".lower()

    def to_dict(self) -> dict:
        return asdict(self)


class Source:
    name = ""
    label = ""
    # ats: one company's board. portal: a job site searched by keyword. website: a careers page.
    kind = "ats"

    def parse_url(self, url: str) -> JobBoard | None:
        """Return the board behind a URL, or None if the URL is not from this source."""
        raise NotImplementedError

    def fetch_board(self, board: JobBoard, client) -> list[dict]:
        """Return normalized jobs. Raises http_client.FetchError when unavailable."""
        raise NotImplementedError

    def boards_for(self, search_terms: list[str]) -> list[JobBoard]:
        """Portals turn role titles into searches. Other sources need boards from elsewhere."""
        return []

    def complete_job(self, job: dict, client) -> dict:
        """Fetch anything the listing left out. Called only for jobs that passed the title filter."""
        return job


def company_from_slug(slug: str) -> str:
    # Board slugs carry no company name and can have a suffix: "brillio-2".
    return re.sub(r"-\d+$", "", slug).replace("-", " ").replace("_", " ").strip().title()
