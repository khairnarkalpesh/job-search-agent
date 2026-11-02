"""Read a resume file and build the structured candidate profile.

Contact details are removed before anything else happens, so they cannot reach
the stored profile or a search query. This rule-based parser is the fallback for
running from the command line; inside Claude, prompts/resume-extraction.md
refines the same profile shape.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from location_matching import countries_in
from skill_taxonomy import SKILL_CATEGORIES, find_skills, seniority_from_title, seniority_from_years, skill_spec
from target_roles import generate_target_roles

SYNTHETIC_MARKER = "SYNTHETIC TEST RESUME"
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}

SECTION_HEADINGS = {
    "summary": ["summary", "professional summary", "profile", "about", "about me", "objective", "career objective"],
    "skills": ["skills", "technical skills", "core skills", "key skills", "technologies", "core competencies", "skills & tools", "tech stack"],
    "experience": ["experience", "work experience", "professional experience", "employment", "employment history", "work history", "career history"],
    "education": ["education", "academic background", "academics", "education & training"],
    "certifications": ["certifications", "certificates", "licenses & certifications", "certifications & licenses"],
    "projects": ["projects", "personal projects", "key projects", "selected projects", "open source"],
    "languages": ["languages", "spoken languages"],
}
HEADING_TO_SECTION = {heading: section for section, headings in SECTION_HEADINGS.items() for heading in headings}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
WEB_LINK = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin\.com|github\.com)/\S+", re.IGNORECASE)
_PHONE = re.compile(r"(?<![\d/-])\+?\d[\d\s().-]{8,}\d(?![\d/-])")
_MINIMUM_PHONE_DIGITS = 9

_MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DATE = r"(?:(?:[A-Za-z]{3,9}\.?\s+|\d{1,2}/)?(?:19|20)\d{2})"
DATE_RANGE = re.compile(rf"({_DATE})\s*(?:-|–|—|to)\s*({_DATE}|present|current|now|today)", re.IGNORECASE)
ROLE_WORD = re.compile(r"\b(engineer|developer|programmer|architect|lead|analyst|consultant|scientist|manager|intern|sde|administrator)\b", re.IGNORECASE)
BULLET = re.compile(r"^[-•*▪●◦‣·]\s*")
_YEARS_STATED = re.compile(r"(\d{1,2})(?:\.\d)?\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}\s+experience", re.IGNORECASE)


class ResumeParseError(Exception):
    pass


MINIMUM_RESUME_TEXT_LENGTH = 50


def read_resume_text(path: str | Path) -> str:
    text = extract_resume_text(path)
    if len(text.strip()) < MINIMUM_RESUME_TEXT_LENGTH:
        raise ResumeParseError(f"{Path(path).name} has almost no extractable text. "
                               "If it is a scanned PDF, provide a text-based PDF, DOCX, TXT or Markdown copy.")
    return text


def extract_resume_text(path: str | Path) -> str:
    """The text a plain parser gets from the file: DOCX body and tables, not headers or text boxes."""
    resume_path = Path(path)
    if not resume_path.is_file():
        raise ResumeParseError(f"Resume not found: {resume_path}")
    suffix = resume_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ResumeParseError(f"Unsupported resume type '{suffix}'. Use PDF, DOCX, TXT or Markdown.")
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(resume_path)).pages)
        elif suffix == ".docx":
            from docx import Document
            document = Document(str(resume_path))
            table_lines = [" | ".join(cell.text for cell in row.cells)
                           for table in document.tables for row in table.rows]
            text = "\n".join([paragraph.text for paragraph in document.paragraphs] + table_lines)
        else:
            text = resume_path.read_text(encoding="utf-8", errors="replace")
    except ResumeParseError:
        raise
    except Exception as error:
        raise ResumeParseError(f"Could not read {resume_path.name}: {error}") from error
    return text


def _blank_if_phone_number(match: re.Match) -> str:
    # A date range such as "2020 - 2024" has the same shape but only 8 digits.
    digit_count = sum(character.isdigit() for character in match.group())
    return " " if digit_count >= _MINIMUM_PHONE_DIGITS else match.group()


def has_phone_number(text: str) -> bool:
    return any(_blank_if_phone_number(match) == " " for match in _PHONE.finditer(text))


def remove_contact_details(text: str) -> str:
    text = EMAIL.sub(" ", text)
    text = WEB_LINK.sub(" ", text)
    return _PHONE.sub(_blank_if_phone_number, text)


def split_into_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("#*_ ").strip() if not BULLET.match(raw_line.strip()) else raw_line.strip()
        if not line:
            continue
        section = HEADING_TO_SECTION.get(line.rstrip(":").lower())
        if section:
            current = section
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return sections


def extract_name(header_lines: list[str]) -> str:
    for line in header_lines[:4]:
        if SYNTHETIC_MARKER in line.upper():
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[^\W\d_][\w.'-]*", word) for word in words) \
                and not ROLE_WORD.search(line) and not countries_in(line):
            return line
    return ""


def extract_location(header_lines: list[str]) -> str:
    """City-level only. A street address on the same line is dropped."""
    for line in header_lines[:8]:
        if SYNTHETIC_MARKER in line.upper():
            continue
        for segment in re.split(r"[|•·]|\s{2,}", line):
            if countries_in(segment):
                parts = [part.strip() for part in segment.split(",") if part.strip()]
                without_street = [part for part in parts if not re.search(r"\d", part)]
                location = ", ".join(without_street[-2:])
                return re.sub(r"^(location|address)\s*:\s*", "", location, flags=re.IGNORECASE)
    return ""


def _parse_month(value: str, reference_date: dt.date) -> tuple[int, int] | None:
    lowered = value.strip().lower()
    if lowered in ("present", "current", "now", "today"):
        return reference_date.year, reference_date.month
    year_match = re.search(r"(?:19|20)\d{2}", lowered)
    if not year_match:
        return None
    year = int(year_match.group())
    month_number = re.match(r"(\d{1,2})/", lowered)
    if month_number:
        return year, min(max(int(month_number.group(1)), 1), 12)
    return year, _MONTHS.get(lowered[:3], 1)


def _split_role_and_company(heading: str, previous_line: str) -> tuple[str, str, bool]:
    """Return (role, company, used_previous_line)."""
    parts = [part.strip(" ,|-–—") for part in re.split(r"\s+[|•·—–-]\s+|\s+at\s+|\s+@\s+|,\s+", heading)]
    parts = [part for part in parts if part]
    used_previous_line = False
    if len(parts) < 2 and previous_line:
        parts = [previous_line, *parts]
        used_previous_line = True
    role = next((part for part in parts if ROLE_WORD.search(part)), "")
    company = next((part for part in parts if part != role and not countries_in(part)), "")
    return role, company, used_previous_line


@dataclass
class ExperienceBlock:
    """One job as written: its heading lines verbatim, what was read from them, and its body."""

    heading_lines: list[str]
    role: str
    company: str
    duration: str
    start: str
    end: str
    body: list[str] = field(default_factory=list)  # bullet markers removed, original order


def group_experience(lines: list[str]) -> tuple[list[str], list[ExperienceBlock]]:
    """Split an Experience section into jobs, each starting at a line with a date range.

    Returns the lines before the first job, and the jobs. A plain line just above a
    dated line can be that job's role or company ("Acme Corp" then "Engineer, 2020 - 2022").
    """
    preamble: list[str] = []
    blocks: list[ExperienceBlock] = []
    previous_plain_line = ""
    for line in lines:
        current_body = blocks[-1].body if blocks else preamble
        date_range = DATE_RANGE.search(line)
        if date_range:
            blocks.append(_start_block(line, date_range, previous_plain_line, current_body))
            previous_plain_line = ""
            continue
        cleaned = BULLET.sub("", line)
        current_body.append(cleaned)
        previous_plain_line = "" if BULLET.match(line) else cleaned
    return preamble, blocks


def _start_block(line: str, date_range: re.Match, previous_plain_line: str, previous_body: list[str]) -> ExperienceBlock:
    heading = (line[:date_range.start()] + " " + line[date_range.end():]).strip(" ()|,-–—")
    role, company, used_previous_line = _split_role_and_company(heading, previous_plain_line)
    heading_lines = [line]
    if used_previous_line:
        if previous_body and previous_body[-1] == previous_plain_line:
            previous_body.pop()  # it was this job's heading, not the last job's bullet
        heading_lines.insert(0, previous_plain_line)
    return ExperienceBlock(heading_lines, role, company, date_range.group(0).strip(),
                           date_range.group(1), date_range.group(2))


def parse_experience(lines: list[str], reference_date: dt.date) -> tuple[list[dict], float | None]:
    entries: list[dict] = []
    employment_periods: list[tuple[int, int]] = []
    for block in group_experience(lines)[1]:
        entry: dict = {"company": block.company, "role": block.role, "duration": block.duration,
                       "technologies": [], "responsibilities": [], "achievements": []}
        for line in block.body:
            bucket = "achievements" if re.search(r"\d+\s*%|\b\d+x\b|\$\d", line) else "responsibilities"
            entry[bucket].append(line)
        entries.append(entry)
        start = _parse_month(block.start, reference_date)
        end = _parse_month(block.end, reference_date)
        if start and end and end >= start:
            employment_periods.append((start[0] * 12 + start[1], end[0] * 12 + end[1]))

    for entry in entries:
        entry["technologies"] = find_skills("\n".join(
            [entry["role"], *entry["responsibilities"], *entry["achievements"]]))

    if not employment_periods:
        return entries, None
    merged_months = 0
    period_start, period_end = None, None
    for start, end in sorted(employment_periods):  # overlapping jobs are not counted twice
        if period_end is None or start > period_end:
            merged_months += (period_end - period_start) if period_end is not None else 0
            period_start, period_end = start, end
        else:
            period_end = max(period_end, end)
    merged_months += period_end - period_start
    return entries, round(merged_months / 12, 1)


def _clean_list(lines: list[str]) -> list[str]:
    return [BULLET.sub("", line) for line in lines]


def build_profile(text: str, reference_date: dt.date | None = None) -> dict:
    reference_date = reference_date or dt.date.today()
    is_synthetic = SYNTHETIC_MARKER in text.upper()
    cleaned_text = remove_contact_details(text)
    sections = split_into_sections(cleaned_text)
    evidence: list[dict] = []

    skills_section_text = "\n".join(sections.get("skills", []))
    listed_skills = set(find_skills(skills_section_text))
    skills_by_category: dict[str, list[str]] = {category: [] for category in SKILL_CATEGORIES}
    for skill in find_skills(cleaned_text):
        skills_by_category[skill_spec(skill).get("cat", "other")].append(skill)
        source = "Explicitly listed in Skills section" if skill in listed_skills else "Mentioned in resume text"
        evidence.append({"item": skill, "type": "explicit", "evidence": source,
                         "confidence": "high" if skill in listed_skills else "medium"})

    experience, computed_years = parse_experience(sections.get("experience", []), reference_date)
    stated_years = _YEARS_STATED.search("\n".join(sections.get("summary", []) + sections.get("header", [])))
    if stated_years:
        years = float(stated_years.group(1))
        evidence.append({"item": f"{years:g} years of experience", "type": "explicit",
                         "evidence": f"Stated in resume: \"{stated_years.group(0)}\"", "confidence": "high"})
    elif computed_years is not None:
        years = computed_years
        evidence.append({"item": f"{years:g} years of experience", "type": "inferred",
                         "evidence": "Calculated from employment dates, overlapping periods counted once",
                         "confidence": "medium"})
    else:
        years = None

    current_role = next((entry["role"] for entry in experience if entry["role"]), "")
    seniority = seniority_from_title(current_role) or seniority_from_years(years)
    if seniority:
        evidence.append({"item": f"Seniority: {seniority}", "type": "inferred",
                         "evidence": "From most recent job title and years of experience", "confidence": "medium"})

    profile = {
        "synthetic": is_synthetic,
        "candidate": {
            "name": extract_name(sections["header"]),
            "location": extract_location(sections["header"]),
            "years_of_experience": years,
            "current_role": current_role,
            "seniority": seniority,
        },
        "skills": skills_by_category,
        "experience": experience,
        "education": _clean_list(sections.get("education", [])),
        "certifications": _clean_list(sections.get("certifications", [])),
        "projects": _clean_list(sections.get("projects", [])),
        "languages": _clean_list(sections.get("languages", [])),
        "target_roles": [],
        "preferred_locations": [],
        "remote_preference": None,
        "evidence": evidence,
    }
    profile["target_roles"] = generate_target_roles(profile)
    for target_role in profile["target_roles"]:
        evidence.append({"item": target_role["title"], "type": "inferred", "evidence": target_role["reason"],
                         "confidence": target_role["confidence"]})
    return profile


def load_profile_from_resume(path: str | Path) -> dict:
    return build_profile(read_resume_text(path))
