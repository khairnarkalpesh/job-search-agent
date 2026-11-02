"""Project paths, the taxonomy file, and skill, role and seniority detection built on it."""
from __future__ import annotations

import datetime as dt
import functools
import os
import re
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
# User data lives outside the skill folder, which a plugin update replaces.
USER_HOME = Path(os.environ.get("JOB_SEARCH_AGENT_HOME") or Path.home() / ".job-search-agent")
DATA_DIR = USER_HOME / "data"
SYNTHETIC_DATA_DIR = USER_HOME / "synthetic_run_output"
PREFERENCES_FILE = USER_HOME / "preferences.yaml"
TAXONOMY_FILE = SKILL_ROOT / "config" / "taxonomy.yaml"

SKILL_CATEGORIES = ["programming_languages", "frameworks", "databases", "cloud", "devops",
                    "ai_ml", "frontend", "backend", "other"]
SENIORITY_LEVELS = ["intern", "junior", "mid", "senior", "staff", "principal"]


def today() -> str:
    return dt.date.today().isoformat()


@functools.lru_cache(maxsize=1)
def taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY_FILE.read_text(encoding="utf-8"))


def _boundary_pattern(term: str) -> str:
    # \b fails around C++, C# and .NET, so boundaries are spelled out.
    return rf"(?<![\w+#.-]){re.escape(term)}(?![\w+#])"


@functools.lru_cache(maxsize=1)
def skill_patterns() -> list[tuple[str, re.Pattern]]:
    patterns = []
    for name, spec in taxonomy()["skills"].items():
        terms = spec.get("aliases") or [name]
        if name not in terms and not spec.get("cs"):
            terms = [name, *terms]
        flags = 0 if spec.get("cs") else re.IGNORECASE
        patterns.append((name, re.compile("|".join(_boundary_pattern(term) for term in terms), flags)))
    return patterns


# "Go to market" and "go-live" use the word, not the language.
_GO_FALSE_POSITIVE = re.compile(r"\bGo(?:\s+(?:to|on|for|beyond|above|deep|back|live|through|from)\b|-)", re.IGNORECASE)


@functools.lru_cache(maxsize=4096)
def _find_skills_cached(text: str) -> tuple[str, ...]:
    found = []
    for name, pattern in skill_patterns():
        if name == "Go":
            if pattern.search(_GO_FALSE_POSITIVE.sub(" ", text)):
                found.append(name)
        elif pattern.search(text):
            found.append(name)
    return tuple(found)


def find_skills(text: str) -> list[str]:
    """Return canonical skill names mentioned in text, in taxonomy order."""
    return list(_find_skills_cached(text))


def surface_form(skill: str, text: str) -> str:
    """The words text uses for a skill ("RESTful APIs" for REST APIs), longest alias first; "" if absent."""
    spec = skill_spec(skill)
    aliases = spec.get("aliases") or [skill]
    if skill not in aliases and not spec.get("cs"):
        aliases = [skill, *aliases]  # the same terms skill_patterns matches
    terms = sorted(aliases, key=len, reverse=True)
    flags = 0 if spec.get("cs") else re.IGNORECASE
    for term in terms:
        match = re.search(_boundary_pattern(term), text, flags)
        if match:
            return match.group()
    return ""


def skill_spec(name: str) -> dict:
    return taxonomy()["skills"].get(name, {})


def classify_skill(job_skill: str, candidate_skills: set[str]) -> tuple[str, str | None]:
    """Compare one job skill with the candidate's skills.

    Returns (EXACT|RELATED|TRANSFERABLE|MISSING, the candidate skill that justifies it).
    """
    if job_skill in candidate_skills:
        return "EXACT", job_skill
    spec = skill_spec(job_skill)
    for candidate_skill in sorted(candidate_skills):
        other = skill_spec(candidate_skill)
        if candidate_skill in spec.get("related", []) or job_skill in other.get("related", []):
            return "RELATED", candidate_skill
    group = spec.get("group")
    if group:
        for candidate_skill in sorted(candidate_skills):
            if skill_spec(candidate_skill).get("group") == group:
                return "TRANSFERABLE", candidate_skill
    return "MISSING", None


def title_family(title: str) -> str | None:
    """Classify a job title into a role family; None when nothing matches."""
    lowered = title.lower()
    for family, spec in taxonomy()["role_families"].items():
        if any(re.search(pattern, lowered) for pattern in spec.get("title_patterns", [])):
            return family
    return None


_SENIORITY_PATTERNS = [
    ("intern", r"\b(intern|internship|apprentice|co-?op)\b"),
    ("principal", r"\b(principal|distinguished|fellow)\b"),
    ("staff", r"\b(staff|lead|architect|tech lead)\b"),
    ("senior", r"\b(senior|sr\.?|iii|iv|l5|sde[- ]?3|engineer 3)\b"),
    ("junior", r"\b(junior|jr\.?|entry[- ]level|new grad|graduate|associate|trainee)\b"),
    ("mid", r"\b(mid[- ]level|intermediate|ii|sde[- ]?2|engineer 2)\b"),
]


def seniority_from_title(title: str) -> str:
    lowered = title.lower()
    for level, pattern in _SENIORITY_PATTERNS:
        if re.search(pattern, lowered):
            return level
    return ""


def seniority_from_years(years: float | None) -> str:
    if years is None:
        return ""
    if years < 2:
        return "junior"
    if years < 5:
        return "mid"
    if years < 9:
        return "senior"
    return "staff"
