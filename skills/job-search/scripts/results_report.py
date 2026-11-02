"""Turn scored jobs into the table and match explanations the user reads."""
from __future__ import annotations

from sources import SOURCES

DETAILED_MATCH_COUNT = 5


def _table_cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def _key_matches(job: dict, limit: int = 4) -> list[str]:
    exact_first = sorted(job["matched_skills"], key=lambda item: (item["importance"] != "required", item["match"] != "EXACT"))
    return [item["skill"] for item in exact_first[:limit]]


def _main_gaps(job: dict, limit: int = 3) -> str:
    major_gaps = [item for item in job["gaps"] if item.startswith("Major Gap")]
    if major_gaps:
        return "Major gap"
    required_gaps = [item.split(" is ")[0] for item in job["gaps"] if " is required" in item]
    return ", ".join(required_gaps[:limit]) or (", ".join(job["missing_skills"][:limit]) or "None found")


def format_results_table(jobs: list[dict]) -> str:
    lines = ["| Score | Role | Company | Location | Key Match | Gaps | Seen |", "|---|---|---|---|---|---|---|"]
    for job in jobs:
        cells = [job["match_score"], job["title"], job["company"], job["location"] or "Not stated",
                 ", ".join(_key_matches(job)) or "None", _main_gaps(job), job["seen"]]
        lines.append("| " + " | ".join(_table_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def format_job_details(job: dict, rank: int) -> str:
    breakdown = job["score_breakdown"]
    lines = [f"# {rank} — {job['title']}", "",
             f"Company:  {job['company']}",
             f"Match:    {job['match_score']}/100 ({job['category']})",
             f"Location: {job['location'] or 'Not stated'}"]
    if job.get("salary"):
        lines.append(f"Salary:   {job['salary']} (as listed)")
    lines += ["", "Score breakdown:"]
    for name in ("skills", "experience", "role", "qualifications", "technology", "location", "seniority"):
        part = breakdown[name]
        lines.append(f"  {name.title():<15}{part['score']:>5g}/{part['max']:<3} {part['detail']}")
    if "cap_applied" in breakdown:
        lines.append(f"  {breakdown['cap_applied']} (was {breakdown['uncapped_total']})")
    lines += ["", "Why it matches:"] + [f"  ✓ {reason}" for reason in job["why_match"]]
    lines += ["", "Potential gaps:"] + ([f"  ⚠ {gap}" for gap in job["gaps"]] or ["  None found"])
    source = SOURCES.get(job["source"])
    lines += ["", f"Listing on {source.label if source else job['source']}: {job['source_url']}"]
    if job.get("application_url") and job["application_url"] != job["source_url"]:
        lines.append(f"Apply: {job['application_url']}")
    return "\n".join(lines)


def format_report(jobs: list[dict], summary: dict) -> str:
    sections = ["TOP MATCHES", "", format_results_table(jobs), ""]
    for rank, job in enumerate(jobs[:DETAILED_MATCH_COUNT], start=1):
        sections += [format_job_details(job, rank), ""]
    hidden = summary.get("below_minimum_score", 0)
    if hidden:
        sections.append(f"{hidden} scored jobs fell below the minimum score. Use --all to see them.")
    return "\n".join(sections)
