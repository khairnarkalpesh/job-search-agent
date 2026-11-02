"""A resume's sections in the order written, including headings a parser would not recognise.

resume_parser.split_into_sections merges sections into the profile and treats an unknown
heading as ordinary text. The ATS check and the optimizer need the document as written:
every heading, duplicates, and the order they come in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from resume_parser import BULLET, HEADING_TO_SECTION

# Words that give away which standard section a home-made heading means.
_SECTION_HINTS = [
    ("experience", r"work|career|employ|job|position|professional|where i"),
    ("skills", r"skill|tech|tool|stack|competenc|expertise|proficien"),
    ("education", r"educat|stud|academ|school|universit|college|qualification"),
    ("projects", r"project|portfolio|built|open source"),
    ("certifications", r"certif|licen|course|training|credential"),
    ("summary", r"summary|about|profile|objective|introduc|who i am"),
    ("achievements", r"award|honou?r|achiev|accomplish|recogni"),
    ("languages", r"language"),
]
_NAME_BLOCK_LINES = 2  # the name and a title line, even in capitals


@dataclass
class Section:
    name: str  # standard name, "header" for the top of the page, "" when not recognised
    heading: str  # as written; empty for the header
    lines: list[str] = field(default_factory=list)  # content as written, stripped
    suggested: str = ""  # the standard section an unrecognised heading most likely means

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _clean_heading(line: str) -> str:
    return line.strip().strip("#*_ ").strip().rstrip(":").strip()


def _looks_like_heading(line: str) -> bool:
    if BULLET.match(line) or re.search(r"[\d@|,;.]|https?:", line):
        return False
    words = _clean_heading(line).split()
    if not 1 <= len(words) <= 5:
        return False
    letters = [character for character in _clean_heading(line) if character.isalpha()]
    return line.lstrip().startswith("#") or line.rstrip().endswith(":") or (len(letters) >= 3 and all(c.isupper() for c in letters))


def suggest_section(heading: str) -> str:
    lowered = heading.lower()
    return next((name for name, pattern in _SECTION_HINTS if re.search(pattern, lowered)), "")


def outline(text: str) -> list[Section]:
    sections = [Section("header", "")]
    seen_lines = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        seen_lines += 1
        known = HEADING_TO_SECTION.get(_clean_heading(line).lower())
        if known and not BULLET.match(line):
            sections.append(Section(known, _clean_heading(line)))
        elif seen_lines > _NAME_BLOCK_LINES and _looks_like_heading(line):
            heading = _clean_heading(line)
            sections.append(Section("", heading, suggested=suggest_section(heading)))
        else:
            sections[-1].lines.append(line)
    return sections


def sections_named(sections: list[Section], name: str) -> list[Section]:
    return [section for section in sections if section.name == name]


def section_lines(sections: list[Section], name: str) -> list[str]:
    return [line for section in sections_named(sections, name) for line in section.lines]


def lines_meaning(sections: list[Section], name: str) -> list[str]:
    """Lines of a section, including those under a home-made heading that means it."""
    return [line for section in sections if name in (section.name, section.suggested) for line in section.lines]
