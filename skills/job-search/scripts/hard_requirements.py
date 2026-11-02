"""Find requirements that cannot be traded off against a high skills score.

Every requirement lands in exactly one list: met, failed or unknown. Anything
the resume does not settle stays unknown; it is never assumed either way.
"""
from __future__ import annotations

import re

from location_matching import LocationMatch, countries_in
from skill_taxonomy import classify_skill, find_skills

MAJOR = "major"
MINOR = "minor"
_MAJOR_YEARS_GAP = 3
# Fundamentals a resume rarely names. Their absence is not evidence of a gap.
_FOUNDATION_SKILLS = {"OOP", "System Design", "Data Structures", "Agile", "Testing", "Git"}

_YEARS_OF_EXPERIENCE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b", re.IGNORECASE)
_EXPERIENCE_CONTEXT = re.compile(r"experience|background|track record|working|building|developing|professional", re.IGNORECASE)
_NOT_JOB_EXPERIENCE = re.compile(r"\b(years old|founded|years ago|for over \d+ years|in the (last|past) \d+ years|year[- ]old)\b", re.IGNORECASE)

_DEGREE_LEVELS = [(3, re.compile(r"\b(ph\.?\s?d|doctorate|doctoral)\b", re.IGNORECASE)),
                  (2, re.compile(r"\b(master'?s?|m\.?s\.?c?\b|m\.?tech|mba|m\.?e\.)\b", re.IGNORECASE)),
                  (1, re.compile(r"\b(bachelor'?s?|b\.?s\.?c?\b|b\.?tech|b\.?e\.|undergraduate|degree)\b", re.IGNORECASE))]
_DEGREE_NAMES = {1: "bachelor's degree", 2: "master's degree", 3: "PhD"}
_NOT_MANDATORY = re.compile(r"or equivalent|equivalent experience|or related experience|preferred|nice to have|a plus|bonus|ideally|desired", re.IGNORECASE)

CERTIFICATION = re.compile(
    r"\b(AWS Certified[\w -]{0,30}|Azure [\w ]{0,20}Certifi\w+|CKA|CKAD|CISSP|CISM|OSCP|PMP|CPA|Security\+|"
    r"Google Cloud [\w ]{0,20}Certifi\w+)", re.IGNORECASE)

_STRICT_WORDS = re.compile(r"\b(must|required|mandatory|essential|non-negotiable)\b", re.IGNORECASE)
_EMPHASIS_WORDS = re.compile(r"\b(strong|expert|expertise|deep|extensive|proficien\w+|solid)\b", re.IGNORECASE)
_ALTERNATIVES = re.compile(r"\bor\b|such as|e\.g\.|for example|like|similar|equivalent|/", re.IGNORECASE)

_WORK_AUTHORIZATION = re.compile(
    r"(authori[sz]ed to work|work authori[sz]ation|right to work|work permit|visa sponsorship|unable to sponsor|"
    r"not (?:able to )?sponsor|without sponsorship|citizen(ship)?\b|security clearance|\bclearance\b)", re.IGNORECASE)
_SPOKEN_LANGUAGE = r"(English|German|French|Spanish|Japanese|Mandarin|Chinese|Korean|Portuguese|Italian|Dutch|Arabic|Hindi|Russian|Polish|Swedish|Hebrew|Turkish)"
_LANGUAGE_REQUIREMENT = re.compile(
    rf"(?:fluen\w+|native|bilingual|business[- ]level|professional (?:working )?proficiency|proficiency)\b[^.\n]{{0,40}}?\b{_SPOKEN_LANGUAGE}\b"
    rf"|\b{_SPOKEN_LANGUAGE}\b[^.\n]{{0,25}}?\b(?:fluen\w+|native|speaking|speaker|required)\b", re.IGNORECASE)


def _requirement(kind: str, requirement: str, detail: str, severity: str = "") -> dict:
    entry = {"type": kind, "requirement": requirement.strip()[:160], "detail": detail}
    if severity:
        entry["severity"] = severity
    return entry


def _core_lines(job: dict) -> list[str]:
    """Lines stating what is required, leaving out anything listed as a preference."""
    preferred = set(job.get("preferred_qualifications", []))
    if job.get("requirements"):
        return [line for line in job["requirements"] if line not in preferred]
    return [line.removeprefix("- ") for line in job.get("description", "").splitlines()
            if line.removeprefix("- ") not in preferred]


def required_years(job: dict) -> tuple[int, int | None, str] | None:
    """Return (minimum, maximum, source line) of the strictest experience requirement."""
    best = None
    for line in _core_lines(job):
        if _NOT_JOB_EXPERIENCE.search(line) or not _EXPERIENCE_CONTEXT.search(line):
            continue
        for match in _YEARS_OF_EXPERIENCE.finditer(line):
            minimum = int(match.group(1))
            maximum = int(match.group(2)) if match.group(2) else None
            if 1 <= minimum <= 25 and (best is None or minimum > best[0]):
                best = (minimum, maximum, line)
    return best


def _check_experience(job, profile, result) -> None:
    requirement = required_years(job)
    if requirement is None:
        return
    minimum, _, line = requirement
    years = profile["candidate"].get("years_of_experience")
    if years is None:
        result["unknown"].append(_requirement("experience", line, "Resume does not establish total years of experience"))
    elif years >= minimum:
        result["met"].append(_requirement("experience", line, f"You have {years:g} years; {minimum}+ asked"))
    else:
        is_major = minimum - years >= _MAJOR_YEARS_GAP
        label = "Major Gap: Required experience is significantly above your experience" if is_major else "Slightly under the experience asked for"
        result["failed"].append(_requirement("experience", line, f"{label} ({minimum}+ required, you have {years:g})",
                                             MAJOR if is_major else MINOR))


def _candidate_degree_level(profile: dict) -> int | None:
    education = "\n".join(profile.get("education", []))
    if not education:
        return None
    return next((level for level, pattern in _DEGREE_LEVELS if pattern.search(education)), None)


def _check_degree(job, profile, result) -> None:
    candidate_level = _candidate_degree_level(profile)
    for line in _core_lines(job):
        required_level = next((level for level, pattern in _DEGREE_LEVELS if pattern.search(line)), None)
        if required_level is None or not re.search(r"degree|bachelor|master|ph\.?d|b\.?tech|b\.?s\b|m\.?s\b", line, re.IGNORECASE):
            continue
        degree_name = _DEGREE_NAMES[required_level]
        flexible = bool(_NOT_MANDATORY.search(line))
        if candidate_level is None:
            result["unknown"].append(_requirement("degree", line, f"Asks for a {degree_name}; resume education not clear"))
        elif candidate_level >= required_level:
            result["met"].append(_requirement("degree", line, f"Your education meets the {degree_name} asked for"))
        elif flexible:
            result["unknown"].append(_requirement("degree", line, f"Prefers a {degree_name} but accepts equivalents"))
        else:
            result["failed"].append(_requirement("degree", line, f"Requires a {degree_name}, above your stated education", MAJOR))
        return


def _check_certifications(job, profile, result) -> None:
    held = " ".join(profile.get("certifications", [])).lower()
    for line in _core_lines(job):
        for match in CERTIFICATION.finditer(line):
            name = match.group(0).strip()
            if name.lower() in held:
                result["met"].append(_requirement("certification", line, f"You hold {name}"))
            elif _STRICT_WORDS.search(line) and not _NOT_MANDATORY.search(line):
                result["failed"].append(_requirement("certification", line, f"Mandatory certification not on resume: {name}", MAJOR))
            else:
                result["unknown"].append(_requirement("certification", line, f"{name} mentioned; not on your resume"))


def _check_mandatory_technologies(job, candidate_skills, result) -> None:
    seen: set[str] = set()
    for line in job.get("requirements", []):
        is_strict = bool(_STRICT_WORDS.search(line))
        if not is_strict and not _EMPHASIS_WORDS.search(line):
            continue
        line_skills = [skill for skill in find_skills(line) if skill not in seen and skill not in _FOUNDATION_SKILLS]
        if not line_skills:
            continue
        verdicts = {skill: classify_skill(skill, candidate_skills)[0] for skill in line_skills}
        missing = [skill for skill, verdict in verdicts.items() if verdict == "MISSING"]
        severity = MAJOR if is_strict else MINOR
        if len(line_skills) > 1 and _ALTERNATIVES.search(line):
            seen.update(line_skills)
            if len(missing) == len(line_skills):
                result["failed"].append(_requirement("technology", line, f"Needs one of: {', '.join(missing)}", severity))
            else:
                result["met"].append(_requirement("technology", line, "You have at least one of the options listed"))
            continue
        seen.update(line_skills)
        for skill in missing:
            result["failed"].append(_requirement("technology", line, f"Required technology not on resume: {skill}", severity))
        if len(missing) < len(line_skills):
            result["met"].append(_requirement("technology", line, f"You have {', '.join(s for s in line_skills if s not in missing)}"))


def _check_work_authorization(job, preferences, result) -> None:
    authorized_countries = set().union(*(countries_in(place) for place in preferences.get("work_authorization") or [])) \
        if preferences.get("work_authorization") else set()
    for line in job.get("description", "").splitlines():
        if not _WORK_AUTHORIZATION.search(line) or len(line) > 400:
            continue
        needed_countries = countries_in(line)
        if re.search(r"clearance|citizen", line, re.IGNORECASE):
            result["unknown"].append(_requirement("work_authorization", line, "Citizenship or clearance condition; cannot be judged from a resume"))
        elif needed_countries and authorized_countries:
            if needed_countries & authorized_countries:
                result["met"].append(_requirement("work_authorization", line, "Matches your saved work authorization"))
            else:
                result["failed"].append(_requirement("work_authorization", line, "Needs work rights you have not listed", MAJOR))
        else:
            result["unknown"].append(_requirement("work_authorization", line, "Check your eligibility; resume does not state work rights"))
        return


def _check_location(location_match: LocationMatch, result) -> None:
    if location_match.status == "match":
        result["met"].append(_requirement("location", location_match.reason, "Location works"))
    elif location_match.status == "mismatch":
        result["failed"].append(_requirement("location", location_match.reason, location_match.reason, MAJOR))
    else:
        result["unknown"].append(_requirement("location", location_match.reason, location_match.reason))


def _check_spoken_languages(job, profile, result) -> None:
    known_languages = " ".join(profile.get("languages", [])).lower()
    checked: set[str] = set()
    for line in _core_lines(job):
        match = _LANGUAGE_REQUIREMENT.search(line)
        if not match:
            continue
        language = (match.group(1) or match.group(2)).title()
        if language in checked or _NOT_MANDATORY.search(line):
            continue
        checked.add(language)
        if language.lower() in known_languages:
            result["met"].append(_requirement("language", line, f"You list {language}"))
        elif language == "English":
            result["met"].append(_requirement("language", line, "Inferred from your resume being written in English"))
        elif known_languages:
            result["failed"].append(_requirement("language", line, f"Requires {language}, not among your languages", MAJOR))
        else:
            result["unknown"].append(_requirement("language", line, f"Requires {language}; resume lists no languages"))


def evaluate_hard_requirements(job: dict, profile: dict, preferences: dict, candidate_skills: set[str],
                               location_match: LocationMatch) -> dict:
    result = {"met": [], "failed": [], "unknown": []}
    _check_experience(job, profile, result)
    _check_degree(job, profile, result)
    _check_certifications(job, profile, result)
    _check_mandatory_technologies(job, candidate_skills, result)
    _check_work_authorization(job, preferences, result)
    _check_location(location_match, result)
    _check_spoken_languages(job, profile, result)
    return {"hard_requirements_met": result["met"], "hard_requirements_failed": result["failed"],
            "unknown_requirements": result["unknown"]}
