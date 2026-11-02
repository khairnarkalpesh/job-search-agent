"""Turn source-specific data into the one job shape the rest of the system uses."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from skill_taxonomy import find_skills

_BLOCK_TAGS = {"p", "div", "br", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "table"}
_SKIP_TAGS = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skipping += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _BLOCK_TAGS or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    # Greenhouse double-escapes its content, so unescape before parsing.
    extractor = _TextExtractor()
    extractor.feed(html.unescape(markup or ""))
    lines = [re.sub(r"[ \t �]+", " ", line).strip() for line in "".join(extractor.parts).splitlines()]
    return "\n".join(line for line in lines if line and line != "-")


_REQUIRED_HEADING = re.compile(
    r"(requirements?|required|qualifications?|what you('|’)?ll need|what you need|what we('|’)?re looking for|"
    r"what we look for|you have|you bring|you should have|you will have|about you|who you are|must[- ]haves?|"
    r"skills (and|&) experience|experience (and|&) skills|your (background|experience|profile|skills)|what you bring|"
    r"we('|’)?d love|ideal candidate|minimum)", re.IGNORECASE)
_PREFERRED_HEADING = re.compile(
    r"(preferred|nice[- ]to[- ]haves?|bonus|good to have|desirable|a plus|plus points|extra credit|"
    r"would be great|it('|’)?s great if|ideally)", re.IGNORECASE)
_OTHER_HEADING = re.compile(
    r"^(about (us|the (company|team|role|job))|benefits|perks|what we offer|why (join|work)|responsibilities|"
    r"what you('|’)?ll do|what you will do|the role|the team|your role|compensation|salary|pay|our (mission|values|culture|team)|"
    r"equal (employment|opportunity)|how to apply|location|interview process|life at|who we are)", re.IGNORECASE)


def _is_heading(line: str) -> bool:
    return len(line) <= 70 and not line.startswith("- ") and not line.endswith((".", ";"))


def split_sections(text: str) -> tuple[list[str], list[str]]:
    """Return (requirements, preferred_qualifications) lines from description text."""
    requirements: list[str] = []
    preferred: list[str] = []
    current = None
    for line in text.splitlines():
        if _is_heading(line):
            if _PREFERRED_HEADING.search(line):
                current = preferred
                continue
            if _REQUIRED_HEADING.search(line):
                current = requirements
                continue
            if _OTHER_HEADING.search(line):
                current = None
                continue
        if current is not None:
            current.append(line.removeprefix("- "))
    if not requirements:
        requirements = [line.removeprefix("- ") for line in text.splitlines()
                        if re.search(r"\b(required|must have|must be|\d+\+? years|experience (with|in))\b", line, re.I)]
    return requirements, preferred


_RESPONSIBILITY_HEADING = re.compile(
    r"^(responsibilities|key responsibilities|what you('|’)?ll do|what you will do|your role|the role|"
    r"in this role|day[- ]to[- ]day|your (impact|mission)|what you('|’)?ll be doing)", re.IGNORECASE)


def responsibility_lines(text: str) -> list[str]:
    """Lines under a Responsibilities-style heading, up to the next heading."""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if _is_heading(line) and (_RESPONSIBILITY_HEADING.search(line) or _REQUIRED_HEADING.search(line)
                                  or _PREFERRED_HEADING.search(line) or _OTHER_HEADING.search(line)):
            inside = bool(_RESPONSIBILITY_HEADING.search(line))
            continue
        if inside:
            lines.append(line.removeprefix("- "))
    return lines


_MONEY = r"[$€£₹] ?\d[\d,]*(?:\.\d+)? ?[kK]?\b"
_SALARY = re.compile(rf"{_MONEY}(?: ?(?:-|–|—|to) ?{_MONEY})?(?: ?(?:USD|EUR|GBP|INR|CAD))?")
_PAY_WORDS = re.compile(r"salary|compensation|\bpay\b|\bbase\b|\bctc\b|per (year|annum)|annual", re.IGNORECASE)
_NOT_PAY_WORDS = re.compile(r"funding|raised|valuation|revenue|series [a-e]\b|investors?|\bARR\b|customers?|bonus|stipend", re.IGNORECASE)


def extract_salary(text: str) -> str:
    """Only returns a pay figure printed in the listing, stated next to a pay word.

    Funding rounds and revenue use the same notation, so a figure alone is not enough.
    """
    for line in text.splitlines():
        if not _PAY_WORDS.search(line) or _NOT_PAY_WORDS.search(line):
            continue
        for match in _SALARY.finditer(line):
            first_amount = re.match(r"[$€£₹] ?([\d,]+)( ?[kK])?", match.group())
            has_thousands_suffix = bool(first_amount.group(2))
            if has_thousands_suffix or len(first_amount.group(1).replace(",", "")) >= 5:
                return match.group().strip(" ,")
    return ""


def detect_remote(location: str, workplace_type: str = "") -> bool | None:
    workplace = workplace_type.lower()
    if workplace == "remote":
        return True
    if workplace in ("onsite", "on-site", "hybrid"):
        return False
    if re.search(r"\b(remote|anywhere|work from home|wfh|distributed)\b", location, re.I):
        return True
    if re.search(r"\b(hybrid|on-?site|in[- ]office)\b", location, re.I):
        return False
    return None


# UTF-8 read as Latin-1 turns é into Ã©, a non-breaking space into Â and a dash into â€“.
_MOJIBAKE_MARKERS = ("Ã", "Â", "â€")


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 text that a source decoded as Latin-1 once already ("MÃ©xico").

    Text that does not decode cleanly is left exactly as it was.
    """
    if not text or not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    for codec in ("latin-1", "cp1252"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def make_job(*, source: str, job_id: str, title: str, company: str, location: str, description: str,
             url: str, application_url: str = "", employment_type: str = "", salary: str = "",
             remote: bool | None = None, workplace_type: str = "", posted_at: str = "",
             board: str = "") -> dict:
    """Build a normalized job. Any missing field stays empty; nothing is guessed.

    Text analysis lives in enrich_job, because some boards hold thousands of
    listings and most are dropped by the title filter before it is needed.
    """
    title = re.sub(r"\s+", " ", repair_mojibake(title or "")).strip()
    location = re.sub(r"\s+", " ", repair_mojibake(location or "")).strip()
    description = repair_mojibake(description or "").strip()
    company = repair_mojibake(company or "")
    return {
        "job_id": f"{source}:{board or company}:{job_id}",
        "title": title,
        "company": (company or "").strip(),
        "location": location,
        "remote": remote if remote is not None else detect_remote(location, workplace_type),
        "workplace_type": workplace_type,
        "employment_type": employment_type,
        "salary": salary,
        "description": description,
        "requirements": [],
        "preferred_qualifications": [],
        "technologies": [],
        "application_url": application_url or url,
        "source": source,
        "source_url": url,
        "posted_at": posted_at,
        "board": board,
    }


def enrich_job(job: dict) -> dict:
    """Add what can only be read from the description. Required before scoring."""
    requirements, preferred = split_sections(job["description"])
    return {
        **job,
        "salary": job["salary"] or extract_salary(job["description"]),
        "requirements": requirements,
        "preferred_qualifications": preferred,
        "technologies": find_skills(f"{job['title']}\n{job['description']}"),
    }
