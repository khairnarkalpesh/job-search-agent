"""Work out which job titles a candidate can realistically target."""
from __future__ import annotations

from skill_taxonomy import taxonomy, title_family

_MINIMUM_RELEVANCE = 0.45
_SIGNALS_FOR_FULL_RELEVANCE = 4
_CURRENT_ROLE_BONUS = 0.25
_MAXIMUM_RELEVANCE_WITHOUT_ROLE_HISTORY = 0.8  # skills alone rank below roles actually held
_FRONTEND_SIGNALS = {"React", "Next.js", "Angular", "Vue.js", "HTML", "CSS"}
_BACKEND_SIGNALS = {"Java", "Spring Boot", "Python", "Django", "Flask", "FastAPI", "Go", "Node.js",
                    "Ruby on Rails", ".NET", "C#", "PHP"}


def candidate_skill_set(profile: dict) -> set[str]:
    return {skill for skills in profile["skills"].values() for skill in skills}


def _confidence(relevance: float) -> str:
    if relevance >= 0.75:
        return "high"
    return "medium" if relevance >= 0.55 else "low"


# Sections where a skill shows real use. One seen only in a project or a course counts half.
_FULL_WEIGHT_SECTIONS = {"skills", "experience", "summary", "header"}
_PROJECT_ONLY_WEIGHT = 0.5


def _signal_weight(skill: str, profile: dict) -> float:
    sources = (profile.get("skill_sources") or {}).get(skill)
    if sources is None or _FULL_WEIGHT_SECTIONS.intersection(sources):
        return 1.0
    return _PROJECT_ONLY_WEIGHT


def generate_target_roles(profile: dict, limit: int = 14, summary: str = "") -> list[dict]:
    """Job titles the resume supports, best first.

    The most recent job title, and the role the summary names ("Frontend engineer with..."),
    lift their role family above families suggested by skills alone.
    """
    skills = candidate_skill_set(profile)
    current_role_family = title_family(profile["candidate"].get("current_role", ""))
    summary_family = title_family(summary[:120]) if summary else None
    demonstrated_skills = {skill for job in profile["experience"] for skill in job["technologies"]}
    target_roles: dict[str, dict] = {}

    for family, spec in taxonomy()["role_families"].items():
        titles = spec.get("titles") or []
        matched_signals = [skill for skill in spec.get("signals", []) if skill in skills]
        if not titles or not matched_signals:
            continue
        if family == "fullstack" and not (skills & _FRONTEND_SIGNALS and skills & _BACKEND_SIGNALS):
            continue
        weight = sum(_signal_weight(skill, profile) for skill in matched_signals)
        relevance = min(weight / _SIGNALS_FOR_FULL_RELEVANCE, 1.0)
        reason = f"Resume shows {', '.join(matched_signals[:5])}"
        if family == current_role_family or (current_role_family == "general_software" and family == "backend"):
            relevance = min(relevance + _CURRENT_ROLE_BONUS, 1.0)
            reason += "; matches most recent role"
        elif family == summary_family:
            relevance = min(relevance + _CURRENT_ROLE_BONUS, 1.0)
            reason += "; the role your summary names"
        else:
            relevance = min(relevance, _MAXIMUM_RELEVANCE_WITHOUT_ROLE_HISTORY)
        if relevance < _MINIMUM_RELEVANCE:
            continue
        for title in titles:
            target_roles[title] = {"title": title, "family": family, "role_relevance": round(relevance, 2),
                                   "confidence": _confidence(relevance), "reason": reason}

    for skill, titles in taxonomy()["language_titles"].items():
        if skill not in demonstrated_skills:
            continue  # a language merely listed is not enough to target it by name
        for title in titles:
            target_roles.setdefault(title, {
                "title": title, "family": "backend", "role_relevance": 0.9, "confidence": "high",
                "reason": f"{skill} used in work experience"})

    ranked = sorted(target_roles.values(), key=lambda role: role["role_relevance"], reverse=True)
    return ranked[:limit]
