"""Transparent 0-100 scoring. Each component is calculated separately and kept in the output."""
from __future__ import annotations

from hard_requirements import MAJOR, describe_years, evaluate_hard_requirements, required_years
from location_matching import candidate_targets, match_location
from skill_taxonomy import (SENIORITY_LEVELS, alternative_groups, classify_skill, find_skills, seniority_from_title,
                            seniority_from_years, skill_spec, taxonomy, title_family)
from target_roles import candidate_skill_set

COMPONENT_MAXIMUMS = {"skills": 30, "experience": 20, "role": 15, "qualifications": 15,
                      "technology": 10, "location": 5, "seniority": 5}
# UNVERIFIED: a fundamental (Data Structures, OOP, Testing...) the resume does not name. Resumes
# rarely spell these out, so absence is not evidence of a gap; it earns half and is shown as unverified.
MATCH_CREDIT = {"EXACT": 1.0, "RELATED": 0.7, "TRANSFERABLE": 0.4, "UNVERIFIED": 0.5, "MISSING": 0.0}
# alternative: another option in an either-or list ("Node.js, Python or PHP"); only the
# best-matched option counts.
SKILL_IMPORTANCE = {"required": 1.0, "preferred": 0.5, "mentioned": 0.25, "alternative": 0.0}
CATEGORY_BANDS = [(90, "Excellent Match"), (80, "Strong Match"), (70, "Good Match"), (60, "Possible Match"), (0, "Low Match")]
TECHNOLOGY_CATEGORIES = {"databases", "cloud", "devops"}

# A disqualifier limits the score however good the rest of the match looks.
SCORE_CAP_ONE_MAJOR_GAP = 64
SCORE_CAP_SEVERAL_MAJOR_GAPS = 49
SCORE_CAP_WRONG_LOCATION = 49
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
    """How each skill the listing names compares with the candidate's, and how much it matters.

    A skill takes the strictest level any part of the listing gives it: required when the
    title, the requirements or the responsibilities name it, even if a "nice to have" list
    repeats it.
    """
    required = set(find_skills("\n".join([job["title"], *job.get("requirements", []),
                                          *job.get("responsibilities", [])])))
    preferred = set(find_skills("\n".join(job.get("preferred_qualifications", [])))) - required
    assessments = []
    for skill in job.get("technologies", []):
        importance = "mentioned"
        if skill in required:
            importance = "required"
        elif skill in preferred:
            importance = "preferred"
        match_type, matched_with = classify_skill(skill, candidate_skills)
        if match_type == "MISSING" and skill_spec(skill).get("foundation"):
            match_type = "UNVERIFIED"
        assessments.append({"skill": skill, "match": match_type, "matched_with": matched_with, "importance": importance})
    _apply_alternatives(job, assessments)
    return assessments


def requirement_label(item: dict) -> str:
    """"GCP, AWS or Azure" for an either-or requirement, the skill alone otherwise."""
    options = [item["skill"], *item.get("alternatives", [])]
    return options[0] if len(options) == 1 else f"{', '.join(options[:-1])} or {options[-1]}"


def _apply_alternatives(job: dict, assessments: list[dict]) -> None:
    """"Node.js, Python or PHP" asks for one of the three, not all three.

    The best-matched option keeps its level and lists the others under "alternatives"; the
    others become "alternative" and weigh nothing, so one requirement is not counted three times.
    """
    by_skill = {item["skill"]: item for item in assessments}
    lines = [*job.get("requirements", []), *job.get("responsibilities", []), *job.get("preferred_qualifications", [])]
    for group in (group for line in lines for group in alternative_groups(line)):
        options = [by_skill[skill] for skill in group if skill in by_skill and by_skill[skill]["importance"] != "alternative"]
        if len(options) < 2:
            continue
        best = max(options, key=lambda item: MATCH_CREDIT[item["match"]])  # the first option on a tie
        best["alternatives"] = [item["skill"] for item in options if item is not best]
        for item in options:
            if item is not best:
                item["importance"] = "alternative"


def _weighted_fraction(assessments: list[dict]) -> float | None:
    total_weight = sum(SKILL_IMPORTANCE[item["importance"]] for item in assessments)
    if not total_weight:
        return None
    earned = sum(SKILL_IMPORTANCE[item["importance"]] * MATCH_CREDIT[item["match"]] for item in assessments)
    fraction = earned / total_weight
    # One or two skills say little: the fraction is pulled toward neutral, so a support or
    # estimation role naming only "Python" cannot take full skill points from that one match.
    counted = len([item for item in assessments if item["importance"] != "alternative"])
    if counted < MINIMUM_RELIABLE_SKILL_COUNT:
        missing = MINIMUM_RELIABLE_SKILL_COUNT - counted
        fraction = (fraction * counted + NEUTRAL_FRACTION * missing) / MINIMUM_RELIABLE_SKILL_COUNT
    return fraction


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
        years_note = f"{describe_years(requirement)} asked, you have {years:g}"

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


def job_seniority(job: dict) -> tuple[str, str]:
    """The level a job asks for, and where that came from.

    Stated years beat the title: a "Senior" role asking for 3-6 years is a mid-level role.
    """
    requirement = required_years(job)
    if requirement:
        minimum, maximum, _ = requirement
        level = seniority_from_years(minimum or maximum)
        if level:
            return level, f"{describe_years(requirement)} asked"
    level = seniority_from_title(job["title"])
    return level, "from the title" if level else ""


def _seniority_fraction(job: dict, profile: dict) -> tuple[float, str]:
    candidate_level = profile["candidate"].get("seniority", "")
    job_level, basis = job_seniority(job)
    if not candidate_level or not job_level:
        return 0.6, "Level not stated"
    distance = abs(SENIORITY_LEVELS.index(candidate_level) - SENIORITY_LEVELS.index(job_level))
    return {0: 1.0, 1: 0.6, 2: 0.2}.get(distance, 0.0), f"Job looks {job_level} ({basis}); you look {candidate_level}"


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
        if item["importance"] in ("mentioned", "alternative"):
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
        if item["importance"] in ("mentioned", "alternative") or item["skill"] in failed_details:
            continue
        if item["match"] == "MISSING" and item.get("alternatives"):
            gaps.append(f"One of {requirement_label(item)} is {item['importance']}; none shown on your resume")
        elif item["match"] == "MISSING":
            gaps.append(f"{item['skill']} is {item['importance']}; not shown on your resume")
        elif item["match"] == "UNVERIFIED":
            gaps.append(f"Unverified: {item['skill']} is {item['importance']}; your resume does not name it "
                        "(coursework or coding contests can show it)")
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
    cap_reason = f"{len(major_gaps)} major gap(s)"
    if len(major_gaps) >= 2:
        score_cap = SCORE_CAP_SEVERAL_MAJOR_GAPS
    elif major_gaps:
        score_cap = SCORE_CAP_ONE_MAJOR_GAP
    if location_match.status == "mismatch":
        # A job the candidate cannot take from where they are is not a near miss, however good the rest is.
        score_cap, cap_reason = min(score_cap or 100, SCORE_CAP_WRONG_LOCATION), "outside your locations"
    final_score = min(uncapped_score, score_cap) if score_cap is not None else uncapped_score
    breakdown["uncapped_total"] = uncapped_score
    if score_cap is not None and uncapped_score > score_cap:
        breakdown["cap_applied"] = f"Limited to {score_cap}: {cap_reason}"

    why_match, gaps = _explain(assessments, breakdown, hard_requirements, location_match)
    return {
        **job,
        "match_score": final_score,
        "category": category_for(final_score),
        "score_breakdown": breakdown,
        "matched_skills": [item for item in assessments if item["match"] not in ("MISSING", "UNVERIFIED")
                           and item["importance"] != "alternative"],
        "missing_skills": [item["skill"] for item in assessments
                           if item["match"] == "MISSING" and item["importance"] != "alternative"],
        "missing_required_skills": [item["skill"] for item in assessments
                                    if item["match"] == "MISSING" and item["importance"] == "required"],
        "missing_labels": [requirement_label(item) for item in assessments
                           if item["match"] == "MISSING" and item["importance"] != "alternative"],
        # The same requirements as the listing words them: "GCP, AWS or Azure" for an either-or list.
        "missing_required_labels": [requirement_label(item) for item in assessments
                                    if item["match"] == "MISSING" and item["importance"] == "required"],
        "unverified_skills": [item["skill"] for item in assessments if item["match"] == "UNVERIFIED"],
        # Credited in part through a neighbouring skill (Docker for Kubernetes), yet still not on the resume.
        "partial_skills": [{"skill": item["skill"], "importance": item["importance"], "match": item["match"],
                            "matched_with": item["matched_with"]}
                           for item in assessments if item["match"] in ("RELATED", "TRANSFERABLE")
                           and item["importance"] != "alternative"],
        "hard_requirements": hard_requirements,
        "why_match": why_match,
        "gaps": gaps,
        "reliable": len(job.get("description", "")) >= MINIMUM_RELIABLE_DESCRIPTION_LENGTH
                    and len(assessments) >= MINIMUM_RELIABLE_SKILL_COUNT,
    }
