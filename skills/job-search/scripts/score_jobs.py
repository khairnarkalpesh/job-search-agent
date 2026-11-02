"""Transparent 0-100 scoring. Each component is calculated separately and kept in the output."""
from __future__ import annotations

from hard_requirements import MAJOR, evaluate_hard_requirements, required_years
from location_matching import candidate_targets, match_location
from skill_taxonomy import (SENIORITY_LEVELS, classify_skill, find_skills, seniority_from_title,
                            seniority_from_years, skill_spec, taxonomy, title_family)
from target_roles import candidate_skill_set

COMPONENT_MAXIMUMS = {"skills": 30, "experience": 20, "role": 15, "qualifications": 15,
                      "technology": 10, "location": 5, "seniority": 5}
MATCH_CREDIT = {"EXACT": 1.0, "RELATED": 0.7, "TRANSFERABLE": 0.4, "MISSING": 0.0}
SKILL_IMPORTANCE = {"required": 1.0, "preferred": 0.5, "mentioned": 0.25}
CATEGORY_BANDS = [(90, "Excellent Match"), (80, "Strong Match"), (70, "Good Match"), (60, "Possible Match"), (0, "Low Match")]
TECHNOLOGY_CATEGORIES = {"databases", "cloud", "devops"}

# A disqualifier limits the score however good the rest of the match looks.
SCORE_CAP_ONE_MAJOR_GAP = 64
SCORE_CAP_SEVERAL_MAJOR_GAPS = 49
NEUTRAL_FRACTION = 0.5  # used where a listing gives nothing to compare, and always disclosed
MINIMUM_RELIABLE_DESCRIPTION_LENGTH = 300
MINIMUM_RELIABLE_SKILL_COUNT = 3  # with fewer, one lucky match would look like a perfect score


def category_for(score: int) -> str:
    return next(label for floor, label in CATEGORY_BANDS if score >= floor)


def _clean_title(title: str) -> str:
    words = title.lower().replace(",", " ").split()
    noise = {"senior", "sr", "sr.", "junior", "jr", "lead", "staff", "principal", "ii", "iii", "i", "iv"}
    return " ".join(word for word in words if word not in noise)


def assess_job_skills(job: dict, candidate_skills: set[str]) -> list[dict]:
    required = find_skills("\n".join([job["title"], *job.get("requirements", [])]))
    preferred = [skill for skill in find_skills("\n".join(job.get("preferred_qualifications", []))) if skill not in required]
    assessments = []
    for skill in job.get("technologies", []):
        importance = "mentioned"
        if skill in required:
            importance = "required"
        elif skill in preferred:
            importance = "preferred"
        match_type, matched_with = classify_skill(skill, candidate_skills)
        assessments.append({"skill": skill, "match": match_type, "matched_with": matched_with, "importance": importance})
    return assessments


def _weighted_fraction(assessments: list[dict]) -> float | None:
    total_weight = sum(SKILL_IMPORTANCE[item["importance"]] for item in assessments)
    if not total_weight:
        return None
    earned = sum(SKILL_IMPORTANCE[item["importance"]] * MATCH_CREDIT[item["match"]] for item in assessments)
    return earned / total_weight


def _experience_fraction(job: dict, profile: dict, assessments: list[dict]) -> tuple[float, str]:
    years = profile["candidate"].get("years_of_experience")
    requirement = required_years(job)
    if years is None or requirement is None:
        years_fit = NEUTRAL_FRACTION
        years_note = "years asked or held not stated"
    else:
        minimum, maximum, _ = requirement
        if years < minimum:
            years_fit = max(0.0, 1 - (minimum - years) * 0.25)
        elif maximum is not None and years > maximum + 3:
            years_fit = 0.7
        else:
            years_fit = 1.0
        years_note = f"{minimum}+ asked, you have {years:g}"

    demonstrated = {skill for entry in profile["experience"] for skill in entry["technologies"]}
    wanted = [item for item in assessments if item["importance"] == "required"]
    used_at_work = [item for item in wanted if item["skill"] in demonstrated]
    relevance = len(used_at_work) / len(wanted) if wanted else NEUTRAL_FRACTION
    fraction = 0.7 * years_fit + 0.3 * relevance
    return fraction, f"{years_note}; {len(used_at_work)}/{len(wanted)} required skills used at work"


def role_fit(title: str, profile: dict) -> tuple[float, str]:
    cleaned_title = _clean_title(title)
    target_roles = profile.get("target_roles", [])
    family = title_family(title)
    target_families = {target["family"] for target in target_roles}
    for target in target_roles:
        # The family check stops "Software Development Engineer in Test" matching a developer target.
        if _clean_title(target["title"]) in cleaned_title and family in (target_families | {"general_software"}):
            return max(0.9, target["role_relevance"]), f"Title matches target role {target['title']}"
    if family in target_families:
        return 0.8, f"Same role family as your targets ({family})"
    if family == "general_software":
        return 0.75, "General software engineering title"
    if family == "unspecified_engineer":
        return 0.4, "Title does not say what kind of engineer"
    adjacent = {neighbour for target in target_families for neighbour in taxonomy()["adjacent_families"].get(target, [])}
    if family in adjacent:
        return 0.5, f"Adjacent role family ({family})"
    return 0.15, f"Outside your target roles ({family or 'unclassified'})"


def _seniority_fraction(job: dict, profile: dict) -> tuple[float, str]:
    candidate_level = profile["candidate"].get("seniority", "")
    requirement = required_years(job)
    job_level = seniority_from_title(job["title"]) or seniority_from_years(requirement[0] if requirement else None)
    if not candidate_level or not job_level:
        return 0.6, "Level not stated"
    distance = abs(SENIORITY_LEVELS.index(candidate_level) - SENIORITY_LEVELS.index(job_level))
    return {0: 1.0, 1: 0.6, 2: 0.2}.get(distance, 0.0), f"Job looks {job_level}; you look {candidate_level}"


def _qualification_fraction(hard_requirements: dict) -> tuple[float, str]:
    met = len(hard_requirements["hard_requirements_met"])
    failed = len(hard_requirements["hard_requirements_failed"])
    unknown = len(hard_requirements["unknown_requirements"])
    total = met + failed + unknown
    if not total:
        return NEUTRAL_FRACTION, "No hard requirements found in listing"
    return (met + 0.5 * unknown) / total, f"{met} met, {failed} failed, {unknown} unknown"


def _component(name: str, fraction: float, detail: str) -> dict:
    maximum = COMPONENT_MAXIMUMS[name]
    return {"score": round(min(max(fraction, 0.0), 1.0) * maximum, 1), "max": maximum, "detail": detail}


def _explain(assessments, breakdown, hard_requirements, location_match) -> tuple[list[str], list[str]]:
    why_match, gaps = [], []
    for item in assessments:
        if item["importance"] == "mentioned":
            continue
        if item["match"] == "EXACT" and len(why_match) < 6:
            why_match.append(f"{item['skill']} is {item['importance']} and on your resume")
        elif item["match"] in ("RELATED", "TRANSFERABLE") and len(why_match) < 6:
            why_match.append(f"{item['skill']} asked; your {item['matched_with']} is {item['match'].lower()}")
    for requirement in hard_requirements["hard_requirements_met"]:
        if requirement["type"] in ("experience", "location", "degree"):
            why_match.append(requirement["detail"] if requirement["type"] != "location" else location_match.reason)
    why_match.append(breakdown["role"]["detail"])

    for requirement in hard_requirements["hard_requirements_failed"]:
        prefix = "Major Gap: " if requirement.get("severity") == MAJOR and "Major Gap" not in requirement["detail"] else ""
        gaps.append(prefix + requirement["detail"])
    failed_details = " ".join(gaps)
    for item in assessments:
        if item["match"] == "MISSING" and item["importance"] != "mentioned" and item["skill"] not in failed_details:
            gaps.append(f"{item['skill']} is {item['importance']}; not shown on your resume")
    for requirement in hard_requirements["unknown_requirements"]:
        gaps.append(f"Unconfirmed: {requirement['detail']}")
    return why_match, gaps[:10]


def score_job(job: dict, profile: dict, preferences: dict | None = None, location_filter: str = "") -> dict:
    preferences = preferences or {}
    candidate_skills = candidate_skill_set(profile)
    location_match = match_location(job, candidate_targets(profile, preferences, location_filter))
    assessments = assess_job_skills(job, candidate_skills)
    hard_requirements = evaluate_hard_requirements(job, profile, preferences, candidate_skills, location_match)

    core = [item for item in assessments if skill_spec(item["skill"]).get("cat") not in TECHNOLOGY_CATEGORIES]
    tooling = [item for item in assessments if skill_spec(item["skill"]).get("cat") in TECHNOLOGY_CATEGORIES]
    skills_fraction = _weighted_fraction(core)
    technology_fraction = _weighted_fraction(tooling)
    experience_fraction, experience_detail = _experience_fraction(job, profile, assessments)
    role_fraction, role_detail = role_fit(job["title"], profile)
    qualification_fraction, qualification_detail = _qualification_fraction(hard_requirements)
    seniority_fraction, seniority_detail = _seniority_fraction(job, profile)
    location_fraction = {"match": 1.0, "partial": 0.6, "unknown": 0.5, "mismatch": 0.0}[location_match.status]

    breakdown = {
        "skills": _component("skills", NEUTRAL_FRACTION if skills_fraction is None else skills_fraction,
                             "No skills found in listing" if skills_fraction is None else f"{len(core)} skills compared"),
        "experience": _component("experience", experience_fraction, experience_detail),
        "role": _component("role", role_fraction, role_detail),
        "qualifications": _component("qualifications", qualification_fraction, qualification_detail),
        "technology": _component("technology", NEUTRAL_FRACTION if technology_fraction is None else technology_fraction,
                                 "No tools named in listing" if technology_fraction is None else f"{len(tooling)} tools compared"),
        "location": _component("location", location_fraction, location_match.reason),
        "seniority": _component("seniority", seniority_fraction, seniority_detail),
    }
    uncapped_score = round(sum(part["score"] for part in breakdown.values()))
    major_gaps = [item for item in hard_requirements["hard_requirements_failed"] if item.get("severity") == MAJOR]
    score_cap = None
    if len(major_gaps) >= 2:
        score_cap = SCORE_CAP_SEVERAL_MAJOR_GAPS
    elif major_gaps:
        score_cap = SCORE_CAP_ONE_MAJOR_GAP
    final_score = min(uncapped_score, score_cap) if score_cap is not None else uncapped_score
    breakdown["uncapped_total"] = uncapped_score
    if score_cap is not None and uncapped_score > score_cap:
        breakdown["cap_applied"] = f"Limited to {score_cap}: {len(major_gaps)} major gap(s)"

    why_match, gaps = _explain(assessments, breakdown, hard_requirements, location_match)
    return {
        **job,
        "match_score": final_score,
        "category": category_for(final_score),
        "score_breakdown": breakdown,
        "matched_skills": [item for item in assessments if item["match"] != "MISSING"],
        "missing_skills": [item["skill"] for item in assessments if item["match"] == "MISSING"],
        "missing_required_skills": [item["skill"] for item in assessments
                                    if item["match"] == "MISSING" and item["importance"] == "required"],
        "hard_requirements": hard_requirements,
        "why_match": why_match,
        "gaps": gaps,
        "reliable": len(job.get("description", "")) >= MINIMUM_RELIABLE_DESCRIPTION_LENGTH
                    and len(assessments) >= MINIMUM_RELIABLE_SKILL_COUNT,
    }
