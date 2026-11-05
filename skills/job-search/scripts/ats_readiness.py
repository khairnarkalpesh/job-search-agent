"""ATS Readiness: can this resume be read and understood by an automated screening system?

An explainable heuristic, not a reproduction of any vendor's algorithm. Six categories:

    Parsing readiness   20   contact details, job titles, employers and dates can be extracted
    Structure           15   standard, recognisable sections in a sensible order
    Keyword coverage    25   the listing's skills appear on the resume, in its wording   (job only)
    Required skills     20   what the listing requires is visible on the resume           (job only)
    Section quality     10   bullets, skills list and summary say something checkable
    Formatting safety   10   nothing that a parser loses or scrambles

Without a job, the two job-only categories are not assessed and the other 55 points are
scaled to 100, which the report states. This is separate from the Job Match score in
score_jobs.py: Job Match asks whether the candidate fits the job; this asks whether the
resume shows it in a form a machine can read. The skill comparison itself is shared.
"""
from __future__ import annotations

import collections
import dataclasses
import functools
import re
from dataclasses import dataclass, field

import yaml

from hard_requirements import evaluate_hard_requirements, required_years
from location_matching import candidate_targets, match_location
from normalize_jobs import responsibility_lines
from resume_layout import LayoutFindings, ResumeDocument
from resume_outline import Section, outline, section_lines, sections_named
from resume_parser import (EMAIL, ROLE_WORD, WEB_LINK, build_profile, extract_location, extract_name,
                           group_experience, has_phone_number, join_wrapped_lines,
                           remove_contact_details)
from score_jobs import SKILL_IMPORTANCE, TECHNOLOGY_CATEGORIES, assess_job_skills, requirement_label
from skill_taxonomy import (SKILL_ROOT, find_skills, seniority_from_title, seniority_from_years, skill_mentions,
                            shared_surface_form, skill_spec, surface_form, term_in_text)

CATEGORY_MAXIMUMS = {"parsing": 20, "structure": 15, "keywords": 25, "required_skills": 20, "sections": 10,
                     "formatting": 10}
CATEGORY_LABELS = {"parsing": "Parsing Readiness", "structure": "Structure", "keywords": "Keyword Coverage",
                   "required_skills": "Required Skills", "sections": "Section Quality", "formatting": "Formatting Safety"}
JOB_ONLY_CATEGORIES = {"keywords", "required_skills"}
LANGUAGE_FILE = SKILL_ROOT / "config" / "resume_language.yaml"

# How much a resume term counts towards a listing term. A parser matching words does not
# know that Kotlin is close to Java, so related skills earn far less here than in Job Match.
ON_RESUME_CREDIT = {"exact": 1.0, "reworded": 0.8, "related": 0.3, "transferable": 0.1, "unverified": 0.0,
                    "missing": 0.0}
HARD_REQUIREMENT_CREDIT = {"met": 1.0, "unknown": 0.5, "failed": 0.0}
RESUME_VISIBLE_REQUIREMENTS = {"experience", "degree", "certification", "language"}
OUTSIDE_BODY_CREDIT = 0.4  # present in the file, but where many parsers do not look
TOP_RECOMMENDATIONS = 5


@functools.lru_cache(maxsize=1)
def resume_language() -> dict:
    return yaml.safe_load(LANGUAGE_FILE.read_text(encoding="utf-8"))


@dataclass
class Finding:
    category: str
    message: str
    points_lost: float = 0.0
    fix: str = ""
    strength: bool = False
    # A real gap, not a wording problem: no edit can fix it, only the candidate can say
    # whether the experience exists. It goes to additional_information_required, not fixes.
    needs_information: bool = False


@dataclass
class Tally:
    """Points earned out of points available in one category, with the reasons."""

    category: str
    earned: float = 0.0
    available: float = 0.0
    findings: list[Finding] = field(default_factory=list)

    def check(self, weight: float, credit: float, strength: str = "", issue: str = "", fix: str = "") -> None:
        credit = min(max(credit, 0.0), 1.0)
        self.available += weight
        self.earned += weight * credit
        if credit >= 1 and strength:
            self.findings.append(Finding(self.category, strength, strength=True))
        elif credit < 1 and issue:
            self.findings.append(Finding(self.category, issue, weight * (1 - credit), fix))

    def deduct(self, points: float, issue: str, fix: str) -> None:
        lost = min(points, self.earned)
        self.earned -= lost
        self.findings.append(Finding(self.category, issue, lost, fix))

    def scaled(self) -> float | None:
        if not self.available:
            return None
        return round(self.earned / self.available * CATEGORY_MAXIMUMS[self.category], 1)


@dataclass
class ResumeView:
    """Everything the checks read, worked out once."""

    document: ResumeDocument
    sections: list[Section]
    profile: dict
    resume_skills: set[str]
    early_career: bool

    @classmethod
    def of(cls, document: ResumeDocument) -> ResumeView:
        sections = outline(document.text)
        profile = build_profile(document.text)
        experience_lines = section_lines(sections, "experience")
        has_other_evidence = bool(section_lines(sections, "projects") or section_lines(sections, "education"))
        return cls(document, sections, profile, set(find_skills(document.text)),
                   early_career=not experience_lines and has_other_evidence)

    def fix_for_missing(self, name: str, fix: str = "") -> str:
        """When a section is "missing" only because its heading is home-made, renaming it is the fix.

        Every check that the misnamed section explains then gives the same fix, and the
        recommendations list it once.
        """
        misnamed = next((section for section in self.sections
                         if not section.name and section.suggested == name and section.lines), None)
        if misnamed:
            return rename_fix(misnamed)
        return fix or f'Add a section headed "{name.title()}".'


def rename_fix(section: Section) -> str:
    if section.suggested:
        return f'Rename "{section.heading}" to "{section.suggested.title()}".'
    return (f'Give "{section.heading}" a standard heading, such as Experience, Skills, Projects, Education, '
            "Certifications or Achievements, or fold its lines into one of those.")


# Parsing readiness ---------------------------------------------------------------------

_LOST_NOTE = " It is only in the page header or a text box, which many parsers skip."


@dataclass
class ParsingChecks:
    """Records each field a parser should extract: its status, and the points it earns."""

    tally: Tally = field(default_factory=lambda: Tally("parsing"))
    checks: list[dict] = field(default_factory=list)

    def record(self, field_name: str, weight: float, found: str, missing: str, fix: str, *,
               in_body: bool, outside_body: bool = False, partial: float | None = None) -> None:
        """A field is clear in the main text, at risk when only outside it, or missing."""
        if partial is not None:
            credit = partial
        elif in_body:
            credit = 1.0
        else:
            credit = OUTSIDE_BODY_CREDIT if outside_body else 0.0
        at_risk = outside_body and not in_body
        self.checks.append({"field": field_name, "status": _status(credit, at_risk),
                            "detail": found if credit >= 1 else missing})
        self.tally.check(weight, credit, issue=missing + (_LOST_NOTE if at_risk else ""), fix=fix)

    def note(self, field_name: str, present: bool, detail: str, status_if_absent: str = "not_found") -> None:
        self.checks.append({"field": field_name, "status": "clear" if present else status_if_absent, "detail": detail})


def _status(credit: float, at_risk: bool) -> str:
    if credit >= 1:
        return "clear"
    if at_risk:
        return "at_risk"
    return "missing" if credit == 0 else "ambiguous"


def assess_parsing(view: ResumeView) -> tuple[Tally, list[dict]]:
    result = ParsingChecks()
    _parse_contact(view, result)
    _parse_experience_fields(view, result)
    education = section_lines(view.sections, "education")
    result.record("education", 1, "Education section found", "No Education section found",
                  view.fix_for_missing("education"),
                  in_body=bool(education))
    listed = find_skills("\n".join(section_lines(view.sections, "skills")))
    result.record("skills", 1, f"{len(listed)} recognisable skills in the Skills section",
                  "No Skills section a parser can read",
                  view.fix_for_missing("skills"),
                  in_body=bool(listed))
    for optional in ("certifications", "projects"):
        lines = section_lines(view.sections, optional)
        result.note(optional, bool(lines), f"{len(lines)} line(s)" if lines else "None (optional)")
    return result.tally, result.checks


def _header_lines(view: ResumeView) -> list[str]:
    """The top of the page as the profile parser reads it: contact details and Markdown marks removed."""
    text = remove_contact_details("\n".join(sections_named(view.sections, "header")[0].lines))
    return [line.strip().strip("#*_ ").strip() for line in text.splitlines() if line.strip()]


def _parse_contact(view: ResumeView, result: ParsingChecks) -> None:
    body, outside = view.document.text, view.document.text_outside_body
    header_lines = _header_lines(view)
    result.record("name", 3, "Name is on the first lines", "No name found on the first lines",
                  "Put your name alone on the first line.", in_body=bool(extract_name(header_lines)),
                  outside_body=bool(extract_name(outside.splitlines())))
    result.record("email", 3, "Email found", "No email found in the main text",
                  "Put your email in the main text under your name, as plain text.",
                  in_body=bool(EMAIL.search(body)), outside_body=bool(EMAIL.search(outside)))
    result.record("phone", 2, "Phone found", "No phone found in the main text",
                  "Put your phone number in the main text under your name, as plain text.",
                  in_body=has_phone_number(body), outside_body=has_phone_number(outside))
    location = extract_location(header_lines)
    result.record("location", 2, f"Location reads as {location}", "No city and country found near the top",
                  "Add your city and country under your name.", in_body=bool(location))
    links = WEB_LINK.findall(body)
    result.note("profile_links", bool(links), f"{len(links)} profile or portfolio link(s)" if links else "None (optional)")


def _parse_experience_fields(view: ResumeView, result: ParsingChecks) -> None:
    entries = view.profile["experience"]
    if view.early_career:
        for field_name in ("job_titles", "employers", "dates"):
            result.note(field_name, False, "No work experience section; read as early career", "not_applicable")
        return
    same_line_fix = 'Write each job as "Title | Employer | Dates" on one line.'
    if not entries:
        dates_fix = 'Give every job a date range on its title line, such as "Jan 2021 - Mar 2023".'
        result.record("dates", 3, "", "No employment dates could be read, so no jobs were recognised",
                      view.fix_for_missing("experience", dates_fix), in_body=False)
        result.record("job_titles", 3, "", "No job titles could be read",
                      view.fix_for_missing("experience", same_line_fix), in_body=False)
        result.record("employers", 2, "", "No employers could be read",
                      view.fix_for_missing("experience", same_line_fix), in_body=False)
        return
    count = len(entries)
    titled = sum(1 for entry in entries if entry["role"])
    named = sum(1 for entry in entries if entry["company"])
    result.record("dates", 3, f"Dates read for {count} job(s)", "", "", in_body=True)
    result.record("job_titles", 3, f"Job title read for all {count} job(s)",
                  f"Job title unclear for {count - titled} of {count} job(s)", same_line_fix,
                  in_body=True, partial=titled / count)
    result.record("employers", 2, f"Employer read for all {count} job(s)",
                  f"Employer unclear for {count - named} of {count} job(s)", same_line_fix,
                  in_body=True, partial=named / count)


# Structure -----------------------------------------------------------------------------

def assess_structure(view: ResumeView) -> tuple[Tally, list[dict]]:
    tally = Tally("structure")
    found = [{"heading": section.heading, "standard": section.name or None, "suggested": section.suggested or None}
             for section in view.sections if section.name != "header"]
    present = {section.name for section in view.sections if section.lines}
    essentials = ([("education", 3), ("skills", 2), ("projects", 3)] if view.early_career
                  else [("experience", 4), ("skills", 2), ("education", 2)])
    for name, weight in essentials:
        tally.check(weight, 1.0 if name in present else 0.0, issue=f"No {name.title()} section",
                    fix=view.fix_for_missing(name))
    if all(name in present for name, _ in essentials):
        tally.findings.append(Finding("structure", "Standard section structure", strength=True))

    # 3 points; each unrecognised heading costs 1.5 until they run out, and every one is reported.
    unknown = [section for section in view.sections if section.name == "" and section.lines]
    if not unknown:
        tally.check(3, 1.0, strength="Section headings are standard names")
    for index, section in enumerate(unknown):
        issue = f'Heading a parser may not recognise: "{section.heading}"'
        if index < 2:
            tally.check(1.5, 0.0, issue=issue, fix=rename_fix(section))
        else:
            tally.findings.append(Finding("structure", issue, 0.0, rename_fix(section)))
    if len(unknown) == 1:
        tally.check(1.5, 1.0)
    repeated = sorted({section.name for section in view.sections if section.name not in ("", "header")
                       and len(sections_named(view.sections, section.name)) > 1})
    tally.check(2, 0.0 if repeated else 1.0, issue=f"Repeated sections: {', '.join(repeated)}; a parser may keep only one",
                fix="Merge each repeated section into one.")
    _assess_order(view, tally)
    return tally, found


def _assess_order(view: ResumeView, tally: Tally) -> None:
    header_text = sections_named(view.sections, "header")[0].text
    tally.check(1, 1.0 if EMAIL.search(header_text) or has_phone_number(header_text) else 0.0,
                issue="Contact details are not at the top of the page", fix="Move your contact details under your name.")
    order = [section.name for section in view.sections]
    years = view.profile["candidate"].get("years_of_experience") or 0
    if "experience" in order and "education" in order and years >= 2:
        tally.check(1, 1.0 if order.index("experience") < order.index("education") else 0.0,
                    issue="Education comes before Experience although you have years of work behind you",
                    fix="Put Experience before Education.")


# Section quality -----------------------------------------------------------------------

def starts_with_action(line: str) -> bool:
    first = re.sub(r"[^a-z-]", "", line.split()[0].lower()) if line.split() else ""
    return first in set(resume_language()["action_verbs"]) or (len(first) > 4 and first.endswith("ed"))


def starts_weak(line: str) -> bool:
    lowered = line.lower()
    return any(lowered.startswith(opener) for opener in resume_language()["weak_openers"])


def work_bullets(view: ResumeView) -> list[str]:
    """Experience bullets, or project lines for an early-career resume."""
    if view.early_career:
        return join_wrapped_lines(section_lines(view.sections, "projects"))
    return [line for block in group_experience(section_lines(view.sections, "experience"))[1] for line in block.body]


def filler_in(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in resume_language()["filler_phrases"] if phrase in lowered]


def overused_terms(text: str) -> list[dict]:
    """Skills repeated often enough, for the length of the resume, to read as keyword stuffing.

    Whole terms are counted: "Tailwind CSS" is a mention of Tailwind CSS, not of CSS.
    """
    language = resume_language()
    counts = collections.Counter(skill for _, _, skill in skill_mentions(text))
    words = max(len(text.split()), 1)
    return [{"term": name, "count": count} for name, count in counts.most_common()
            if count >= language["overuse_count"] and count / words >= language["overuse_share"]]


def assess_sections(view: ResumeView) -> Tally:
    tally = Tally("sections")
    _assess_bullets(view, tally)
    _assess_skills_list(view, tally)
    _assess_summary(view, tally)
    return tally


def _assess_bullets(view: ResumeView, tally: Tally) -> None:
    bullets = work_bullets(view)
    where = "project descriptions" if view.early_career else "job bullets"
    if not bullets:
        tally.check(5, 0.0, issue=f"No {where} to read",
                    fix=view.fix_for_missing("projects" if view.early_career else "experience",
                                             "Describe what you did in two to five bullets per job."))
        return
    language = resume_language()
    blocks = [] if view.early_career else group_experience(section_lines(view.sections, "experience"))[1]
    thin = [block for block in blocks if len(block.body) < 2]
    tally.check(1.5, 1 - len(thin) / len(blocks) if blocks else 1.0, strength="Every job has at least two bullets",
                issue=f"{len(thin)} job(s) have fewer than two bullets",
                fix="Give each job at least two bullets saying what you built or ran.")
    active = [line for line in bullets if starts_with_action(line)]
    tally.check(1.0, len(active) / len(bullets) / 0.6, strength=f"Most {where} start with an action verb",
                issue=f"{len(bullets) - len(active)} of {len(bullets)} {where} do not start with an action verb",
                fix="Start each bullet with what you did: Built, Designed, Migrated, Led.")
    weak = [line for line in bullets if starts_weak(line)]
    tally.check(0.5, 0.0 if weak else 1.0,
                issue=f'{len(weak)} bullet(s) describe a duty ("Responsible for", "Worked on") instead of what was done',
                fix='Rewrite "Responsible for X" as what you did with X, keeping the same facts.')
    with_tools = [line for line in bullets if find_skills(line)]
    tally.check(1, len(with_tools) / len(bullets) / 0.5, strength=f"Technologies are named in the {where}",
                issue=f"Only {len(with_tools)} of {len(bullets)} {where} name a technology",
                fix="Name the tools you used in the bullet where you used them.")
    long_bullets = [line for line in bullets if len(line.split()) > language["max_bullet_words"]]
    tally.check(0.5, 0.0 if long_bullets else 1.0, issue=f"{len(long_bullets)} bullet(s) over {language['max_bullet_words']} words",
                fix="Split long bullets into one achievement each.")
    measured = [line for line in bullets if re.search(r"\d", line)]
    tally.check(0.5, 1.0 if measured else 0.0, strength="Some outcomes are measured",
                issue="No bullet gives a figure (scale, time, users, money)",
                fix="If you have real figures for an outcome, add them. Never estimate one.")


def _assess_skills_list(view: ResumeView, tally: Tally) -> None:
    lines = section_lines(view.sections, "skills")
    listed = find_skills("\n".join(lines))
    if not listed:
        tally.check(3, 0.0, issue="No skills list to assess", fix=view.fix_for_missing("skills"))
        return
    limit = resume_language()["max_listed_skills"]
    item_count = len([item for line in lines for item in re.split(r"[,;|•·]", line) if item.strip()])
    tally.check(1, 0.0 if item_count > limit else 1.0, strength="Skills list is a readable length",
                issue=f"{item_count} items in the Skills list; the relevant ones get lost",
                fix="Keep the skills that matter for the roles you want; drop ones you would not want to be asked about.")
    tally.check(1, 0.0 if item_count > 12 and len(lines) == 1 else 1.0, strength="Skills are grouped",
                issue=f"{item_count} skills on one line, ungrouped",
                fix='Group them by kind, one line each: "Languages: ...", "Frameworks: ...".')
    used = set(find_skills("\n".join(work_bullets(view) + section_lines(view.sections, "projects"))))
    learning = set(view.profile.get("skills_learning", []))  # "Java (learning)" is honest as written
    listed_only = [skill for skill in listed if skill not in used and skill not in learning]
    # Full credit while at least half the listed skills show up in use.
    tally.check(1, (1 - len(listed_only) / len(listed)) / 0.5,
                strength="Listed skills are backed by your experience or projects",
                issue=f"Listed but never shown in use: {', '.join(listed_only[:8])}",
                fix="Where you used these at work or in a project, say so in that bullet. Drop any you have not used.")
    for item in overused_terms(view.document.text):
        tally.deduct(1, f"{item['term']} appears {item['count']} times; this reads as keyword stuffing",
                     f"Mention {item['term']} where it was used, not in every line.")
    if view.document.layout.hidden_text:
        tally.deduct(2, "The file contains hidden text (white, tiny or hidden); screeners treat this as keyword stuffing",
                     "Delete the hidden text.")


def _assess_summary(view: ResumeView, tally: Tally) -> None:
    summary = " ".join(section_lines(view.sections, "summary"))
    if not summary:
        tally.findings.append(Finding("sections", "No summary. It is optional; two lines naming your target role help a reader."))
        return
    words = len(summary.split())
    tally.check(0.5, 1.0 if 12 <= words <= 90 else 0.0, issue=f"Summary is {words} words",
                fix="Keep the summary to two or three sentences.")
    filler = filler_in(summary)
    tally.check(0.75, 0.0 if filler else 1.0, strength="Summary avoids filler",
                issue=f"Summary uses filler: {', '.join(filler)}",
                fix="Replace each phrase with something checkable: a role, a domain, a technology you used.")
    tally.check(0.75, 1.0 if ROLE_WORD.search(summary) and find_skills(summary) else 0.0,
                strength="Summary names a role and relevant skills",
                issue="Summary does not name a role and the skills behind it",
                fix='Open with your role and main tools, e.g. "Backend engineer working in Java and Spring Boot".')


# Formatting safety ---------------------------------------------------------------------

# Built from code points so the ranges survive any editor: icon fonts use the private-use
# area; pictographs and dingbats include the phone and envelope symbols used as labels.
_PRIVATE_USE = re.compile(f"[{chr(0xE000)}-{chr(0xF8FF)}]")
_PICTOGRAPHS = re.compile(f"[{chr(0x2600)}-{chr(0x27BF)}{chr(0x1F300)}-{chr(0x1FAFF)}]")
_GARBLED = re.compile(rf"\(cid:\d+\)|{chr(0xFFFD)}")
_DECORATIVE_LINE = re.compile(r"^[\s_=~*•·━─═-]{5,}$", re.MULTILINE)
_LAYOUT_TABLE_SHARE = 0.3

Risk = tuple[float, str, str, str]  # points, name, what happens, what to do


def _severity(points: float) -> str:
    if points >= 2.5:
        return "high"
    return "medium" if points >= 1 else "low"


def assess_formatting(view: ResumeView) -> tuple[Tally, list[dict]]:
    tally = Tally("formatting", earned=10, available=10)
    risks: list[dict] = []
    for points, name, detail, fix in _layout_risks(view.document.layout) + _character_risks(view.document.text):
        risks.append({"risk": name, "severity": _severity(points), "detail": detail, "fix": fix})
        tally.deduct(points, detail, fix)
    if not risks:
        tally.findings.append(Finding("formatting", "No tables, columns, text boxes or icons that a parser could lose",
                                      strength=True))
    return tally, risks


def _layout_risks(layout: LayoutFindings) -> list[Risk]:
    checks = (_table_risk, _column_risk, _text_box_risk, _header_footer_risk, _image_risk)
    return [risk for check in checks for risk in check(layout)]


def _table_risk(layout: LayoutFindings) -> list[Risk]:
    if layout.markdown_tables:
        return [(1.0, "tables", "The text contains a table; it may come out as one run-on line",
                 "Use plain lines instead of a table.")]
    if not layout.tables:
        return []
    fix = "Move the content out of tables into plain lines."
    if layout.table_text_share > _LAYOUT_TABLE_SHARE:
        return [(3.0, "tables", (f"{layout.tables} table(s) hold {round(layout.table_text_share * 100)}% of the text; "
                                 "many parsers read tables cell by cell and lose which date belongs to which job"), fix)]
    return [(1.0, "tables", f"{layout.tables} small table(s); low risk unless they hold job titles or dates", fix)]


def _column_risk(layout: LayoutFindings) -> list[Risk]:
    if layout.columns <= 1:
        return []
    mixed = "parsers read across the page and mix the columns together"
    if layout.columns_inferred:
        return [(2.0, "columns", f"The PDF looks like it has two columns; {mixed}", "Use a single column.")]
    return [(3.0, "columns", f"The document is set in {layout.columns} columns; {mixed}", "Use a single column.")]


def _text_box_risk(layout: LayoutFindings) -> list[Risk]:
    if not layout.text_box_text:
        return []
    return [(3.0, "text_boxes", (f"{len(layout.text_box_text)} characters are inside text boxes, which most parsers "
                                 "skip entirely"), "Move text-box content into the body of the document.")]


def _header_footer_risk(layout: LayoutFindings) -> list[Risk]:
    if not layout.header_footer_text:
        return []
    if EMAIL.search(layout.header_footer_text) or has_phone_number(layout.header_footer_text):
        return [(2.0, "header_footer", "Contact details are in the page header or footer, which some parsers ignore",
                 "Put your contact details in the body, under your name.")]
    return [(0.5, "header_footer", "Text in the page header or footer may be ignored", "Put that text in the body.")]


def _image_risk(layout: LayoutFindings) -> list[Risk]:
    if layout.image_only_pages:
        return [(4.0, "image_pages", f"{layout.image_only_pages} page(s) are images with no text layer",
                 "Export the resume as a text PDF or DOCX.")]
    if layout.images:
        return [(0.5, "images", f"{layout.images} image(s); parsers ignore them, which is fine unless one holds text",
                 "Make sure nothing important is only in an image.")]
    return []


def _character_risks(text: str) -> list[Risk]:
    found = []
    if _PRIVATE_USE.search(text):
        found.append((1.5, "icons", ("Icon-font characters found; parsers turn them into blanks or junk, so an icon "
                                     "used instead of a word (a phone symbol for 'Phone') carries no meaning"),
                      "Use words or plain labels instead of icons."))
    if _PICTOGRAPHS.search(text):
        found.append((0.5, "symbols", "Pictographs or emoji found; some parsers drop or mangle them",
                      "Replace symbols with plain text."))
    if _GARBLED.search(text):
        found.append((2.0, "encoding", "Some characters do not decode (font encoding); a parser sees junk there",
                      "Re-export with standard fonts, or save as DOCX."))
    if _DECORATIVE_LINE.search(text):
        found.append((0.5, "decoration", "Decorative lines of symbols; harmless to most parsers but read as text by some",
                      "Use spacing or a heading instead of symbol lines."))
    return found


# Keyword coverage and required skills (job only) ---------------------------------------

SHOWN_ON_RESUME = ("exact", "reworded")


def compare_terms(job: dict, view: ResumeView, evidence_skills: set[str]) -> list[dict]:
    """Every skill the listing names, and how the resume shows it.

    supported_elsewhere: the resume does not show the skill, but the reviewed profile does,
    so naming it would be true. Only such terms are ever suggested for adding.
    """
    listing_text = f"{job['title']}\n{job['description']}"
    terms = []
    for item in assess_job_skills(job, view.resume_skills):
        if item["importance"] == "alternative":
            continue  # another option of an either-or list; the best-matched option stands for it
        # A listing may name a skill several ways ("Jest or Playwright", "Git ... GitHub"); the one the
        # resume also uses is the listing's term, so a shared word is never reported as reworded.
        job_term = (shared_surface_form(item["skill"], listing_text, view.document.text)
                    or surface_form(item["skill"], listing_text) or item["skill"])
        on_resume = item["match"].lower()
        resume_term = item["matched_with"] or ""
        if on_resume == "exact":
            if term_in_text(item["skill"], job_term, view.document.text):
                resume_term = job_term
            else:
                resume_term = surface_form(item["skill"], view.document.text)
            on_resume = "exact" if resume_term.lower() == job_term.lower() else "reworded"
        terms.append({"skill": item["skill"], "label": requirement_label(item), "job_term": job_term,
                      "importance": item["importance"],
                      "on_resume": on_resume, "resume_term": resume_term,
                      "supported_elsewhere": on_resume not in SHOWN_ON_RESUME and item["skill"] in evidence_skills,
                      "category": skill_spec(item["skill"]).get("cat", "other")})
    return terms


def assess_keywords(terms: list[dict]) -> Tally:
    tally = Tally("keywords")
    if not terms:
        return tally
    for term in terms:
        tally.check(SKILL_IMPORTANCE[term["importance"]], ON_RESUME_CREDIT[term["on_resume"]])
    exact = [term for term in terms if term["on_resume"] == "exact"]
    if len(exact) >= len(terms) * 0.6:
        tally.findings.append(Finding("keywords", f"{len(exact)} of {len(terms)} skills in the listing appear on your "
                                      "resume in the same words", strength=True))
    _add_term_findings(tally, [term for term in terms if term["importance"] != "required"],
                       lambda term: SKILL_IMPORTANCE[term["importance"]])
    return tally


def _add_term_findings(tally: Tally, chosen: list[dict], weight_of) -> None:
    """One finding per kind of shortfall, so a long listing does not produce a wall of issues."""
    reworded = [term for term in chosen if term["on_resume"] == "reworded"]
    supported = [term for term in chosen if term["supported_elsewhere"]]
    absent = [term for term in chosen if term["on_resume"] not in SHOWN_ON_RESUME and not term["supported_elsewhere"]]

    def add(terms: list[dict], issue: str, fix: str, needs_information: bool = False) -> None:
        if terms:
            lost = sum(weight_of(term) * (1 - ON_RESUME_CREDIT[term["on_resume"]]) for term in terms)
            tally.findings.append(Finding(tally.category, issue, lost, fix, needs_information=needs_information))

    wording = ", ".join(f'"{term["job_term"]}" (you wrote "{term["resume_term"]}")' for term in reworded)
    add(reworded, f"The listing and your resume word these differently: {wording}",
        f"Use the listing's wording once, where you describe that work: {wording}.")
    names = ", ".join(term["skill"] for term in supported)
    add(supported, f"Your profile shows these, but this resume never names them: {names}",
        f"Name them where you used them: {names}.")
    for term in absent:
        name = term.get("label") or term["skill"]
        one_of = "any one of " if name != term["skill"] else ""
        if term["on_resume"] == "unverified":
            add([term], f"{name} is asked for and not named on your resume ({term['importance']})",
                f"If you have {name} (coursework, coding contests, work), name it where it shows; "
                "otherwise leave it out.", needs_information=True)
        else:
            add([term], f"Not on your resume: {one_of}{name} ({term['importance']})",
                f"Have you used {one_of}{name}? If so, say where; it is not added without that.",
                needs_information=True)


REQUIRED_SKILL_POINTS = 15
REQUIRED_QUALIFICATION_POINTS = 5


def assess_required(terms: list[dict], hard_requirements: dict) -> Tally:
    tally = Tally("required_skills")
    required = [term for term in terms if term["importance"] == "required"]
    for term in required:
        tally.check(REQUIRED_SKILL_POINTS / len(required), ON_RESUME_CREDIT[term["on_resume"]])
    if required and all(term["on_resume"] in ("exact", "reworded") for term in required):
        tally.findings.append(Finding("required_skills", f"All {len(required)} required skills appear on your resume",
                                      strength=True))
    _add_term_findings(tally, required, lambda term: REQUIRED_SKILL_POINTS / len(required))
    visible = [(status, item) for status, key in (("met", "hard_requirements_met"), ("failed", "hard_requirements_failed"),
                                                  ("unknown", "unknown_requirements"))
               for item in hard_requirements[key] if item["type"] in RESUME_VISIBLE_REQUIREMENTS]
    for status, item in visible:
        tally.check(REQUIRED_QUALIFICATION_POINTS / len(visible), HARD_REQUIREMENT_CREDIT[status],
                    issue=f"{item['detail']} (asked: \"{item['requirement'][:80]}\")",
                    fix="State this plainly on the resume if it is true; if it is not, it is a real gap, not a wording problem.")
    return tally


def job_requirements(job: dict, terms: list[dict], view: ResumeView, hard_requirements: dict, location_match) -> dict:
    def statuses(kind: str) -> list[dict]:
        return [{"status": status, "requirement": item["requirement"], "detail": item["detail"]}
                for status, key in (("met", "hard_requirements_met"), ("failed", "hard_requirements_failed"),
                                    ("unknown", "unknown_requirements"))
                for item in hard_requirements[key] if item["type"] == kind]

    def brief(term: dict) -> dict:
        return {key: term[key] for key in ("skill", "label", "job_term", "on_resume", "resume_term",
                                           "supported_elsewhere")}

    responsibilities = responsibility_lines(job["description"])
    responsibility_skills = find_skills("\n".join(responsibilities))
    years = required_years(job)
    return {
        "required": [brief(term) for term in terms if term["importance"] == "required"],
        "preferred": [brief(term) for term in terms if term["importance"] == "preferred"],
        "responsibilities": {"lines": len(responsibilities), "skills": responsibility_skills,
                             "skills_on_resume": [skill for skill in responsibility_skills if skill in view.resume_skills]},
        "technology": [brief(term) for term in terms if term["category"] in TECHNOLOGY_CATEGORIES],
        "experience": {"asked": f"{years[0]}+ years" if years else None,
                       "resume_shows": view.profile["candidate"].get("years_of_experience"), "checks": statuses("experience")},
        "education": statuses("degree"),
        "certifications": statuses("certification"),
        "location": {"listing": job.get("location", ""), "remote": job.get("remote"), "status": location_match.status,
                     "detail": location_match.reason},
        "seniority": {"listing": seniority_from_title(job["title"]) or seniority_from_years(years[0] if years else None) or None,
                      "resume": view.profile["candidate"].get("seniority") or None},
    }


# Putting it together -------------------------------------------------------------------

def assess_resume(document: ResumeDocument, job: dict | None = None, evidence_skills: set[str] | None = None) -> dict:
    """The ATS readiness report for a resume, for one job when a job is given.

    evidence_skills are skills the candidate is known to have from elsewhere (the reviewed
    profile). A listing term the resume lacks is only suggested when it is in this set.
    """
    view = ResumeView.of(document)
    parsing, parsing_checks = assess_parsing(view)
    structure, sections_found = assess_structure(view)
    formatting, formatting_risks = assess_formatting(view)
    tallies = {"parsing": parsing, "structure": structure, "sections": assess_sections(view), "formatting": formatting}
    report: dict = {"mode": "job" if job else "general", "parsing_checks": parsing_checks,
                    "sections_found": sections_found, "formatting_risks": formatting_risks,
                    "overused_terms": overused_terms(document.text),
                    "unrecognized_skills": view.profile.get("unrecognized_skills", []),
                    "keywords": None, "job_requirements": None, "job": None}
    if job:
        terms = compare_terms(job, view, evidence_skills or set())
        location_match = match_location(job, candidate_targets(view.profile, {}))
        hard_requirements = evaluate_hard_requirements(job, view.profile, {}, view.resume_skills, location_match)
        tallies["keywords"] = assess_keywords(terms)
        tallies["required_skills"] = assess_required(terms, hard_requirements)
        report["keywords"] = _keyword_summary(terms)
        report["job_requirements"] = job_requirements(job, terms, view, hard_requirements, location_match)
        report["job"] = {"title": job["title"], "company": job.get("company", ""), "source_url": job.get("source_url", "")}
    return {**_score(tallies, job_given=job is not None), **report, **_explanations(tallies)}


def _keyword_summary(terms: list[dict]) -> dict:
    return {
        "exact": [term["skill"] for term in terms if term["on_resume"] == "exact"],
        "related": [{"job_term": term["job_term"], "resume_term": term["resume_term"], "kind": term["on_resume"]}
                    for term in terms if term["on_resume"] in ("reworded", "related", "transferable")],
        "missing": [{"skill": term["skill"], "importance": term["importance"], "supported_elsewhere": term["supported_elsewhere"]}
                    for term in terms if term["on_resume"] in ("missing", "related", "transferable")],
    }


def _not_assessed_reason(name: str, job_given: bool) -> str:
    if name not in JOB_ONLY_CATEGORIES:
        return "Nothing to assess"
    return "The listing names no skills or requirements to compare" if job_given else "Needs a job description"


def _score(tallies: dict[str, Tally], job_given: bool) -> dict:
    category_scores: dict[str, dict] = {}
    points_available, earned = 0, 0.0
    for name, maximum in CATEGORY_MAXIMUMS.items():
        tally = tallies.get(name)
        score = tally.scaled() if tally else None
        if tally is None or score is None:
            detail = _not_assessed_reason(name, job_given)
        else:
            detail = f"{round(tally.earned, 1):g} of {round(tally.available, 1):g} points"
            points_available += maximum
            earned += score
        category_scores[name] = {"score": score, "max": maximum, "detail": detail}
    return {"ats_score": round(earned / points_available * 100) if points_available else 0,
            "points_assessed": points_available, "category_scores": category_scores}


def _explanations(tallies: dict[str, Tally]) -> dict:
    findings = [finding for tally in tallies.values() for finding in _scaled_findings(tally)]
    issues = sorted((finding for finding in findings if not finding.strength), key=lambda item: -item.points_lost)
    recommendations: list[dict] = []
    seen: set[str] = set()
    for finding in issues:
        if finding.fix and finding.fix not in seen and finding.points_lost > 0 and not finding.needs_information:
            seen.add(finding.fix)
            recommendations.append({"priority": len(recommendations) + 1, "category": finding.category,
                                    "action": finding.fix, "because": finding.message,
                                    "points_at_stake": round(finding.points_lost, 1)})
    additional = list(dict.fromkeys(finding.fix for finding in issues if finding.needs_information))
    return {"strengths": [finding.message for finding in findings if finding.strength],
            "issues": [{"category": finding.category, "message": finding.message, "points_lost": round(finding.points_lost, 1)}
                       for finding in issues],
            "recommendations": recommendations[:TOP_RECOMMENDATIONS],
            "additional_information_required": additional}


def _scaled_findings(tally: Tally) -> list[Finding]:
    """Points lost in a category's own units, converted to the category's share of 100."""
    if not tally.available:
        return [finding for finding in tally.findings if finding.strength or not finding.points_lost]
    factor = CATEGORY_MAXIMUMS[tally.category] / tally.available
    return [dataclasses.replace(finding, points_lost=finding.points_lost * factor) for finding in tally.findings]


# Text output ---------------------------------------------------------------------------

def format_ats_report(report: dict) -> str:
    lines = ["ATS READINESS", f"{report['ats_score']} / 100", ""]
    if report["mode"] == "general":
        lines += ["No job description given: Keyword Coverage and Required Skills are not assessed, and the other",
                  f"{report['points_assessed']} points are scaled to 100. Give a job for a job-specific check.", ""]
    else:
        job = report["job"]
        lines += [f"Checked against: {job['title']}" + (f" at {job['company']}" if job["company"] else ""), ""]
    for name, part in report["category_scores"].items():
        value = "not assessed" if part["score"] is None else f"{part['score']:g} / {part['max']}"
        lines.append(f"{CATEGORY_LABELS[name]:<20}{value}")
    lines += ["", "Strengths"] + ([f"✓ {item}" for item in report["strengths"]] or ["  None stood out"])
    lines += ["", "Issues"] + ([f"⚠ {item['message']}" for item in report["issues"]] or ["  None found"])
    if report["recommendations"]:
        lines += ["", "Priority Fixes", ""]
        lines += [f"{item['priority']}. {item['action']}" for item in report["recommendations"]]
    lines += ["", "This is a readiness heuristic. No tool can reproduce a specific employer's screening system."]
    return "\n".join(lines)


STRONG_MATCH = 75
WORTH_A_LOOK = 60
READS_WELL = 75


def verdict(ats_report: dict, scored_job: dict) -> str:
    """One line on what to do, from the three measures; the numbers below it still stand apart."""
    match_score, ats_score = scored_job["match_score"], ats_report["ats_score"]
    fixes = len(ats_report["recommendations"])
    major = [gap for gap in scored_job.get("gaps", []) if gap.startswith("Major Gap")]
    if major:
        return f"Probably skip: {major[0].removeprefix('Major Gap: ')}."
    if match_score >= STRONG_MATCH and ats_score >= READS_WELL:
        return "Apply: strong fit, and the resume shows it."
    if match_score >= STRONG_MATCH:
        return f"Apply, after fixing the resume: strong fit, but {fixes} fix(es) would help it read (/resume-optimize)."
    if match_score >= WORTH_A_LOOK:
        missing = _missing_required(scored_job)
        return ("Worth applying if you can speak to the gaps: " + ", ".join(missing[:3]) + "." if missing
                else "Worth applying: a reasonable fit with no required skill missing.")
    return "Probably skip: a weak fit for your profile."


def _missing_required(scored_job: dict) -> list[str]:
    return scored_job.get("missing_required_labels") or scored_job.get("missing_required_skills") or []


def format_separate_scores(ats_report: dict, scored_job: dict) -> str:
    missing = _missing_required(scored_job)
    gap_line = (f"{len(missing)} required skill(s) missing for this job: {', '.join(missing)}" if missing
                else "No required skills missing for this job")
    return "\n".join([
        f"VERDICT: {verdict(ats_report, scored_job)}",
        "",
        "THREE SEPARATE MEASURES",
        f"  ATS Readiness  {ats_report['ats_score']:>3} / 100   Can this resume be parsed and understood for this job?",
        f"  Job Match      {scored_job['match_score']:>3} / 100   How well do you fit this job? (against your saved profile)",
        f"  Skill Gap      {gap_line}. Across all your saved jobs: /job-gaps",
    ])


def compare_reports(before: dict, after: dict) -> dict:
    return {
        "ats_score": {"before": before["ats_score"], "after": after["ats_score"],
                      "change": after["ats_score"] - before["ats_score"]},
        "categories": {name: {"before": before["category_scores"][name]["score"],
                              "after": after["category_scores"][name]["score"]} for name in CATEGORY_MAXIMUMS},
        "issues_resolved": [item["message"] for item in before["issues"]
                            if item["message"] not in {other["message"] for other in after["issues"]}],
        "issues_new": [item["message"] for item in after["issues"]
                       if item["message"] not in {other["message"] for other in before["issues"]}],
    }
