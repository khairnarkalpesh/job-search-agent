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


def generate_target_roles(profile: dict, limit: int = 14) -> list[dict]:
    skills = candidate_skill_set(profile)
    current_role_family = title_family(profile["candidate"].get("current_role", ""))
    demonstrated_skills = {skill for job in profile["experience"] for skill in job["technologies"]}
    target_roles: dict[str, dict] = {}

    for family, spec in taxonomy()["role_families"].items():
        titles = spec.get("titles") or []
        matched_signals = [skill for skill in spec.get("signals", []) if skill in skills]
        if not titles or not matched_signals:
            continue
        if family == "fullstack" and not (skills & _FRONTEND_SIGNALS and skills & _BACKEND_SIGNALS):
            continue
        relevance = min(len(matched_signals) / _SIGNALS_FOR_FULL_RELEVANCE, 1.0)
        reason = f"Resume shows {', '.join(matched_signals[:5])}"
        if family == current_role_family or (current_role_family == "general_software" and family == "backend"):
            relevance = min(relevance + _CURRENT_ROLE_BONUS, 1.0)
            reason += "; matches most recent role"
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
