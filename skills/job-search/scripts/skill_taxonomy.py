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
    # Mentions, not raw pattern hits: "Tailwind CSS" names Tailwind CSS, and "Spring Boot"
    # names Spring Boot, without also claiming CSS or the Spring Framework.
    mentioned = {skill for _, _, skill in skill_mentions(text)}
    return tuple(name for name, _ in skill_patterns() if name in mentioned)


def find_skills(text: str) -> list[str]:
    """Return canonical skill names mentioned in text, in taxonomy order."""
    return list(_find_skills_cached(text))


def skill_mentions(text: str) -> list[tuple[int, int, str]]:
    """Every mention of a skill as (start, end, skill), in order, with no overlaps.

    Where terms overlap the longer wins, so "Tailwind CSS" is one mention of Tailwind CSS,
    not also one of CSS.
    """
    masked = _GO_FALSE_POSITIVE.sub(lambda match: " " * len(match.group()), text)
    spans = [(match.start(), match.end(), name)
             for name, pattern in skill_patterns()
             for match in pattern.finditer(masked if name == "Go" else text)]
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        if not kept or span[0] >= kept[-1][1]:
            kept.append(span)
    return kept


# Between two skills of an either-or list: commas, "or", "/" and "and/or", nothing else.
_SEPARATOR_TOKENS = re.compile(r"\band/or\b|\bor\b|\beither\b|[,/\s]", re.IGNORECASE)
_CHOICE_WORD = re.compile(r"/|\bor\b", re.IGNORECASE)
_MAX_SEPARATOR_LENGTH = 16


def _is_list_separator(text: str) -> bool:
    return len(text) <= _MAX_SEPARATOR_LENGTH and not _SEPARATOR_TOKENS.sub("", text)


def alternative_groups(text: str) -> list[list[str]]:
    """Skills offered as alternatives: "Node.js, Python or PHP" gives [[Node.js, Python, PHP]].

    A group is a run of skills separated only by commas, "or" or "/", with at least one
    "or" or "/" in it. "React and TypeScript" and "React, TypeScript, Redux" are not groups.
    """
    runs: list[tuple[list[str], bool]] = []  # each run of listed skills, and whether it offers a choice
    previous_end = 0
    for start, end, skill in skill_mentions(text):
        separator = text[previous_end:start]
        if runs and _is_list_separator(separator):
            skills, has_choice = runs[-1]
            runs[-1] = (skills + [skill] if skill not in skills else skills,
                        has_choice or bool(_CHOICE_WORD.search(separator)))
        else:
            runs.append(([skill], False))
        previous_end = end
    return [skills for skills, has_choice in runs if has_choice and len(skills) > 1]


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


def shared_surface_form(skill: str, text: str, other: str) -> str:
    """The words text uses for a skill that other uses too, longest first; "" if they share none."""
    spec = skill_spec(skill)
    aliases = spec.get("aliases") or [skill]
    if skill not in aliases and not spec.get("cs"):
        aliases = [skill, *aliases]
    flags = 0 if spec.get("cs") else re.IGNORECASE
    for term in sorted(aliases, key=len, reverse=True):
        match = re.search(_boundary_pattern(term), text, flags)
        if match and term_in_text(skill, match.group(), other):
            return match.group()
    return ""


def term_in_text(skill: str, term: str, text: str) -> bool:
    """True when text uses exactly these words for the skill, as a whole term."""
    flags = 0 if skill_spec(skill).get("cs") else re.IGNORECASE
    return bool(term) and re.search(_boundary_pattern(term), text, flags) is not None


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
