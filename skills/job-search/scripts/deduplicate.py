"""Remove repeat listings, strongest evidence first: URL, job ID, identity, then description text."""
from __future__ import annotations

import re
import urllib.parse

from skill_taxonomy import seniority_from_title

DESCRIPTION_SIMILARITY_THRESHOLD = 0.92


# Query parameters that only say where a click came from. Everything else may name the job
# (gh_jid, token, jobId), so it is kept: dropping it collapsed whole boards into one listing.
_TRACKING_PARAMETERS = re.compile(r"^(utm_\w+|ref|referrer|source|src|gclid|fbclid|mc_cid|mc_eid|lever-source|lever-origin|gh_src)$")


def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.lower())
    query = sorted((key, value) for key, value in urllib.parse.parse_qsl(parts.query)
                   if not _TRACKING_PARAMETERS.match(key))
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    return f"{parts.netloc}{parts.path.rstrip('/').removesuffix('/apply')}{suffix}"


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def role_key(title: str) -> str:
    """Title without a trailing place or requisition: "Java Developer - Pune" is "java developer"."""
    return normalize_text(re.split(r" [-–—|] ", title, maxsplit=1)[0])


def _word_triples(text: str) -> set[tuple[str, ...]]:
    words = normalize_text(text).split()
    return {tuple(words[index:index + 3]) for index in range(len(words) - 2)}


def description_similarity(first: str, second: str) -> float:
    first_triples, second_triples = _word_triples(first), _word_triples(second)
    if not first_triples or not second_triples:
        return 0.0
    return len(first_triples & second_triples) / len(first_triples | second_triples)


def deduplicate_jobs(jobs: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Return (unique jobs, count removed per rule).

    Listings repeated per office keep the first copy, with the rest recorded in
    other_locations. Only jobs with the same role name are compared by text, so
    shared company boilerplate cannot collapse distinct jobs.
    """
    unique_jobs: list[dict] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    seen_identities: set[tuple[str, str, str]] = set()
    jobs_by_company_role: dict[tuple[str, str], list[dict]] = {}
    removed = {"application_url": 0, "job_id": 0, "company_title_location": 0, "description_similarity": 0}

    for job in jobs:
        url = normalize_url(job.get("application_url") or job.get("source_url", ""))
        identity = (normalize_text(job.get("company", "")), normalize_text(job.get("title", "")),
                    normalize_text(job.get("location", "")))
        if url in seen_urls:
            removed["application_url"] += 1
            continue
        if job["job_id"] in seen_ids:
            removed["job_id"] += 1
            continue
        if identity in seen_identities:
            removed["company_title_location"] += 1
            continue
        company_role = (identity[0], role_key(job.get("title", "")))
        same_role = next((other for other in jobs_by_company_role.get(company_role, [])
                          if seniority_from_title(other["title"]) == seniority_from_title(job["title"])
                          and description_similarity(other["description"], job["description"]) >= DESCRIPTION_SIMILARITY_THRESHOLD), None)
        if same_role:
            same_role.setdefault("other_locations", []).append(job.get("location", ""))
            removed["description_similarity"] += 1
            continue
        seen_urls.add(url)
        seen_ids.add(job["job_id"])
        seen_identities.add(identity)
        jobs_by_company_role.setdefault(company_role, []).append(job)
        unique_jobs.append(job)
    return unique_jobs, removed
