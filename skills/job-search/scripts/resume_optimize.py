#!/usr/bin/env python
"""Make a resume stronger for a target job without adding anything that is not true.

    python scripts/resume_optimize.py plan   --resume resume.docx [--url ... | --text-file job.txt]
    python scripts/resume_optimize.py draft  --resume resume.docx [--url ... | --text-file job.txt]
    python scripts/resume_optimize.py verify --resume resume.docx --optimized optimized_resume.md [job]
    python scripts/resume_optimize.py export --optimized optimized_resume.md --output optimized_resume.docx

plan    what to change and why: the ATS report, the facts the rewrite must keep to, which
        skills to put first, which listing terms not to add, and what information is missing.
draft   a safe first version: standard headings, skills grouped with the job's first, the
        most relevant bullets and projects first, filler removed. Wording is unchanged.
verify  rejects a rewrite that adds an employer, title, date, skill, figure, certification
        or education detail, or loses one, or that breaks the structure (a bullet split in
        half, a location line turned into a bullet, a bullet moved to another employer);
        then compares ATS Readiness before and after.
export  writes a single-column DOCX from the Markdown resume.

Rewording bullets and the summary is Claude's job, following prompts/resume-optimization.md;
verify is what holds that rewording to the facts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ats_readiness import (CATEGORY_LABELS, ResumeView, assess_resume, compare_reports, filler_in, resume_language,
                           starts_weak, starts_with_action, work_bullets)
from http_client import FetchError
from job_storage import load_preferences, write_json
from match_job import add_job_arguments, load_profile, read_job
from resume_facts import ResumeFacts, dropped_facts, unsupported_claims
from resume_layout import ResumeDocument, inspect_resume
from resume_outline import lines_meaning, outline
from resume_parser import (BULLET, CORE_SECTIONS, SYNTHETIC_MARKER, ResumeParseError, group_experience,
                           group_projects, skill_list_items)
from score_jobs import assess_job_skills, score_job
from search_jobs import choose_data_dir
from skill_taxonomy import find_skills, skill_mentions, skill_spec, surface_form
from target_roles import candidate_skill_set

PLAN_FILE = "optimization_plan.json"
DRAFT_FILE = "optimized_resume.md"
VERIFIED_EXIT_CODE = 0
REJECTED_EXIT_CODE = 3
SECTION_ORDER = CORE_SECTIONS
EARLY_CAREER_ORDER = ["summary", "skills", "projects", "education", "experience", "certifications", "achievements",
                      "languages"]
SKILL_GROUP_LABELS = {"programming_languages": "Languages", "frameworks": "Frameworks", "backend": "Backend",
                      "frontend": "Frontend", "databases": "Databases", "cloud": "Cloud", "devops": "DevOps",
                      "ai_ml": "AI/ML", "other": "Other"}
IMPORTANCE_RANK = {"required": 0, "preferred": 1, "mentioned": 2, "alternative": 2}
MIN_BULLET_WORDS = 4  # "Bengaluru, Karnataka" or "Remote | IT Services" is a heading line, not a bullet
SAME_BULLET_OVERLAP = 0.5


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Target a resume at a job without adding anything untrue.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "draft", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--resume", required=True, help="The original resume: PDF, DOCX, TXT or Markdown")
        add_job_arguments(command, required=False)
        command.add_argument("--profile", help="candidate_profile.json to use (default: the saved one)")
        command.add_argument("--data-dir", help="Where to save output (default: your data folder)")
        command.add_argument("--json", action="store_true", help="Print the result as JSON")
        if name == "draft":
            command.add_argument("--output", help=f"Where to write the draft (default: {DRAFT_FILE} in the data folder)")
        if name == "verify":
            command.add_argument("--optimized", required=True, help="The rewritten resume to check")
    export = commands.add_parser("export")
    export.add_argument("--optimized", required=True, help="The Markdown resume to export")
    export.add_argument("--output", required=True, help="The .docx file to write")
    return parser.parse_args(argv)


# What the job asks for, ranked --------------------------------------------------------

def job_relevance(job: dict | None) -> dict[str, int]:
    """Each skill the listing names, with its rank: required 0, preferred 1, mentioned 2."""
    if not job:
        return {}
    return {item["skill"]: IMPORTANCE_RANK[item["importance"]] for item in assess_job_skills(job, set())}


def _line_relevance(line: str, relevance: dict[str, int]) -> int:
    """Lower is more relevant: the best-ranked job skill the line names, 3 when none."""
    return min((relevance[skill] for skill in find_skills(line) if skill in relevance), default=3)


def order_by_relevance(lines: list[str], relevance: dict[str, int]) -> list[str]:
    return sorted(lines, key=lambda line: _line_relevance(line, relevance))  # stable: ties keep their order


def order_projects(lines: list[str], relevance: dict[str, int]) -> list[list[str]]:
    """Whole projects, most relevant first; a project's bullets stay with it, in their order."""
    projects = group_projects(lines)
    return sorted(projects, key=lambda project: min(_line_relevance(line, relevance) for line in project))


# The plan ---------------------------------------------------------------------------

def build_plan(document: ResumeDocument, job: dict | None, profile: dict | None) -> dict:
    evidence = candidate_skill_set(profile) if profile else set()
    report = assess_resume(document, job, evidence)
    view = ResumeView.of(document)
    terms = report["job_requirements"] or {}
    keyword_terms = (terms.get("required", []) + terms.get("preferred", [])) if job else []
    relevance = job_relevance(job)
    bullets = work_bullets(view)
    scored = score_job(job, profile, load_preferences()) if job and profile else None
    return {
        "ats": report,
        "job_match": {key: scored[key] for key in ("match_score", "category", "missing_required_skills", "gaps")}
        if scored else None,
        "facts": ResumeFacts.of(document.text).to_dict(),
        "emphasise": [term["skill"] for kind in ("required", "preferred") for term in _by_weight(terms.get(kind, []), job)
                      if job and term["on_resume"] in ("exact", "reworded")],
        "use_job_wording": [{"job_term": term["job_term"], "resume_term": term["resume_term"]}
                            for term in keyword_terms if term["on_resume"] == "reworded"],
        "supported_not_shown": [term["skill"] for term in keyword_terms
                                if term["on_resume"] not in ("exact", "reworded") and term["supported_elsewhere"]],
        "do_not_add": [term.get("label") or term["skill"] for term in keyword_terms
                       if term["on_resume"] not in ("exact", "reworded") and not term["supported_elsewhere"]],
        "skills_order": sorted(view.resume_skills, key=lambda skill: (relevance.get(skill, 3), skill.lower())),
        "projects_order": [project[0] for project in order_projects(lines_meaning(view.sections, "projects"),
                                                                    relevance)],
        "bullets_to_strengthen": _weak_bullets(bullets),
        "filler_to_remove": filler_in(document.text),
        "headings_to_rename": [{"from": item["heading"], "to": item["suggested"].title()}
                               for item in report["sections_found"] if not item["standard"] and item["suggested"]
                            and item["suggested"].lower() != item["heading"].lower()],
        "formatting_fixes": [risk["fix"] for risk in report["formatting_risks"]],
        "additional_information_required": _missing_information(report, view),
    }


def _by_weight(terms: list[dict], job: dict | None) -> list[dict]:
    """Terms of one level, the technologies the role is about before foundations (Git, OOP,
    Testing), then the skills the listing names most often first; ties keep listing order."""
    if not job:
        return terms
    counts: dict[str, int] = {}
    for _, _, skill in skill_mentions(f"{job['title']}\n{job['description']}"):
        counts[skill] = counts.get(skill, 0) + 1
    return sorted(terms, key=lambda term: (bool(skill_spec(term["skill"]).get("foundation")),
                                           -counts.get(term["skill"], 0)))


def _weak_bullets(bullets: list[str]) -> list[dict]:
    limit = resume_language()["max_bullet_words"]
    weak = []
    for line in bullets:
        if starts_weak(line):
            weak.append({"bullet": line, "reason": "describes a duty; start with what you did"})
        elif not starts_with_action(line):
            weak.append({"bullet": line, "reason": "does not start with an action verb"})
        elif len(line.split()) > limit:
            weak.append({"bullet": line, "reason": f"over {limit} words"})
    return weak


def _missing_information(report: dict, view: ResumeView) -> list[str]:
    """Questions for the user. Nothing in this list may be filled in without an answer."""
    required = (report["job_requirements"] or {}).get("required", [])
    needed = [f"Have you used {term['skill']}? If so, where? It is not added without that."
              if term.get("label", term["skill"]) == term["skill"] else
              f"Have you used any one of {term['label']}? If so, which, and where? It is not added without that."
              for term in required if term["on_resume"] not in ("exact", "reworded") and not term["supported_elsewhere"]]
    if not any(re.search(r"\d", line) for line in work_bullets(view)):
        needed.append("Any real figures for your outcomes (scale, time saved, users, money). None will be estimated.")
    for check in report["parsing_checks"]:
        if check["status"] in ("missing", "ambiguous") and check["field"] in ("job_titles", "employers", "dates", "location"):
            needed.append(f"{check['detail']}: please supply it.")
    return needed


# The draft --------------------------------------------------------------------------

def _strip_symbols(line: str) -> str:
    """Icon-font glyphs and pictographs carry no text for a parser."""
    return re.sub(f"[{chr(0xE000)}-{chr(0xF8FF)}{chr(0x2600)}-{chr(0x27BF)}{chr(0x1F300)}-{chr(0x1FAFF)}]", "", line).strip()


def remove_filler(text: str) -> str:
    for phrase in resume_language()["filler_phrases"]:
        text = re.sub(rf"\b{re.escape(phrase)}\b,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,")
    text = re.sub(r"^(?:and|&)\s+", "", text, flags=re.IGNORECASE)  # "Hard-working and backend engineer"
    return text[:1].upper() + text[1:]


def group_skills(lines: list[str], relevance: dict[str, int], job_wording: dict[str, str]) -> list[str]:
    """Skills grouped by kind, job skills first in each group. Where the listing names a skill
    differently, its wording is added beside the resume's: "REST APIs (RESTful services)".
    Items the taxonomy does not know stay, under Other."""
    groups: dict[str, list[tuple[int, str]]] = {label: [] for label in SKILL_GROUP_LABELS.values()}
    for item in skill_list_items(lines):
        # "Spring Boot" also matches the Spring alias; the skill named by the longest match is the one meant.
        skill = max(find_skills(item), key=lambda name: len(surface_form(name, item)), default=None)
        if skill is None:
            groups["Other"].append((3, item))
            continue
        label = SKILL_GROUP_LABELS.get(skill_spec(skill).get("cat", "other"), "Other")
        job_term = job_wording.get(skill, "")
        shown = f"{item} ({job_term})" if job_term and job_term.lower() not in item.lower() else item
        groups[label].append((relevance.get(skill, 3), shown))
    return [f"{label}: {', '.join(name for _, name in sorted(items, key=lambda pair: pair[0]))}"
            for label, items in groups.items() if items]


def _experience_lines(lines: list[str], relevance: dict[str, int]) -> list[str]:
    preamble, blocks = group_experience(lines)
    rendered = list(preamble)
    for block in blocks:
        rendered += ["", *[BULLET.sub("", line) for line in block.heading_lines]]
        rendered += [f"- {line}" for line in order_by_relevance(block.body, relevance)]
    return rendered


def _project_lines(project: list[str]) -> list[str]:
    """A titled project keeps its title as a plain line; a one-line project is a bullet."""
    if len(project) == 1:
        return [f"- {project[0]}"]
    return ["", project[0], *[f"- {line}" for line in project[1:]]]


def build_draft(document: ResumeDocument, job: dict | None) -> str:
    """A reordered, ATS-safe Markdown version of the resume. Every line comes from the original."""
    sections = outline(document.text)
    relevance = job_relevance(job)
    report = assess_resume(document, job)
    wording = {term["skill"]: term["job_term"] for term in ((report["job_requirements"] or {}).get("required", [])
                                                            + (report["job_requirements"] or {}).get("preferred", []))
               if term["on_resume"] == "reworded"}
    grouped: dict[str, tuple[str, list[str]]] = {}
    for section in sections[1:]:
        # Standard sections get the standard heading; others ("Hobbies", "Volunteering") keep their own.
        standard = next((name for name in (section.name, section.suggested) if name in CORE_SECTIONS), "")
        key = standard or section.heading.lower()
        grouped.setdefault(key, (standard.title() or section.heading.title(), []))[1].extend(section.lines)
    early_career = ResumeView.of(document).early_career
    order = EARLY_CAREER_ORDER if early_career else SECTION_ORDER
    keys = [key for key in order if key in grouped] + [key for key in grouped if key not in order]

    out = [_strip_symbols(line) for line in sections[0].lines]
    for key in keys:
        title, lines = grouped[key]
        if key == "summary":
            body = [remove_filler(" ".join(lines))]
        elif key == "skills":
            body = group_skills(lines, relevance, wording)
        elif key == "experience":
            body = _experience_lines(lines, relevance)
        elif key == "projects":
            body = [line for project in order_projects(lines, relevance) for line in _project_lines(project)]
        else:  # one bullet style everywhere: "•" and "*" become "-"
            body = [f"- {BULLET.sub('', line)}" if BULLET.match(line) else line for line in lines]
        out += ["", f"## {title}", *body]
    return "\n".join(out).strip() + "\n"


# Verify -----------------------------------------------------------------------------

def _words(line: str) -> set[str]:
    return set(re.findall(r"\w+", line.lower()))


def _employer(block) -> str:
    return block.company or block.role or block.duration


def structure_problems(original: ResumeDocument, rewritten: ResumeDocument) -> list[dict]:
    """Experience bullets that are no longer whole, or no longer under the job they came from.

    The fact check cannot see these: every word is still true, but the resume is broken.
    A rewritten bullet is traced to the original bullet sharing most of its words; jobs are
    matched by their dates, which the fact check already holds fixed.
    """
    _, before = group_experience(lines_meaning(outline(original.text), "experience"))
    _, after = group_experience(lines_meaning(outline(rewritten.text), "experience"))
    origin = [(_words(bullet), block) for block in before for bullet in block.body]
    problems = []
    for block in after:
        for bullet in block.body:
            words = _words(bullet)
            if len(words) < MIN_BULLET_WORDS:
                problems.append({"kind": "not a bullet", "value": bullet, "reason": f"under {_employer(block)}; "
                                 "a location or heading line, or a piece of a wrapped line"})
            elif bullet[:1].islower():
                problems.append({"kind": "split bullet", "value": bullet,
                                 "reason": "starts mid-sentence; rejoin it to the bullet it was cut from"})
            else:
                overlap, source = max(((len(words & known) / len(words | known), owner) for known, owner in origin),
                                      key=lambda pair: pair[0], default=(0, None))
                if source and overlap >= SAME_BULLET_OVERLAP and (source.start, source.end) != (block.start, block.end):
                    problems.append({"kind": "moved bullet", "value": bullet,
                                     "reason": f"came from {_employer(source)}, now under {_employer(block)}"})
    return problems


def verify(original: ResumeDocument, rewritten: ResumeDocument, job: dict | None, evidence_skills: set[str]) -> dict:
    original_facts, rewritten_facts = ResumeFacts.of(original.text), ResumeFacts.of(rewritten.text)
    claims = unsupported_claims(original_facts, rewritten_facts, evidence_skills)
    dropped = dropped_facts(original_facts, rewritten_facts)
    broken = structure_problems(original, rewritten)
    before = assess_resume(original, job, evidence_skills)
    after = assess_resume(rewritten, job, evidence_skills)
    return {"passed": not claims and not dropped and not broken, "unsupported_claims": claims,
            "dropped_facts": dropped, "structure_problems": broken,
            "comparison": compare_reports(before, after), "before": before, "after": after}


def format_verification(result: dict) -> str:
    lines = []
    if result["unsupported_claims"]:
        lines += ["REJECTED: the rewrite states things the original resume does not", ""]
        lines += [f"  ✗ {item['kind']}: {item['value']} ({item['reason']})" for item in result["unsupported_claims"]]
    if result["dropped_facts"]:
        lines += ["", "REJECTED: the rewrite lost facts from the original", ""]
        lines += [f"  ✗ {item['kind']}: {item['value']} ({item['reason']})" for item in result["dropped_facts"]]
    if result["structure_problems"]:
        lines += ["", "REJECTED: the rewrite breaks the resume's structure", ""]
        lines += [f"  ✗ {item['kind']}: {item['value']} ({item['reason']})" for item in result["structure_problems"]]
    if result["passed"]:
        lines += ["VERIFIED: every employer, title, date, skill, figure, certification and education detail",
                  "comes from the original resume, none was lost, and every bullet is whole and under its job."]
    comparison = result["comparison"]
    overall = comparison["ats_score"]
    lines += ["", "ATS READINESS, BEFORE AND AFTER", "",
              f"  {'Overall':<20}{overall['before']:>6} → {overall['after']:<6}({overall['change']:+d})"]
    for name, scores in comparison["categories"].items():
        if scores["before"] is None and scores["after"] is None:
            continue
        lines.append(f"  {CATEGORY_LABELS[name]:<20}{scores['before']!s:>6} → {scores['after']!s}")
    if comparison["issues_resolved"]:
        lines += ["", "Resolved:"] + [f"  ✓ {issue}" for issue in comparison["issues_resolved"]]
    if comparison["issues_new"]:
        lines += ["", "New issues:"] + [f"  ⚠ {issue}" for issue in comparison["issues_new"]]
    if not result["passed"]:
        lines += ["", "The after score does not count until the rewrite is fixed: an invented claim can raise",
                  "a score without making the resume any truer."]
    return "\n".join(lines)


# Export -----------------------------------------------------------------------------

def export_docx(markdown: str, output: Path) -> None:
    """One column, standard headings, real bullets: nothing a parser has to work around."""
    from docx import Document
    document = Document()
    for raw_line in markdown.splitlines():
        line = re.sub(r"\*\*|__|`", "", raw_line).strip()
        if not line:
            continue
        if line.startswith("## "):
            document.add_heading(line[3:], level=1)
        elif line.startswith("# "):
            document.add_heading(line[2:], level=0)
        elif BULLET.match(line):
            document.add_paragraph(BULLET.sub("", line), style="List Bullet")
        else:
            document.add_paragraph(line)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))


# Commands ---------------------------------------------------------------------------

def _load_inputs(arguments: argparse.Namespace, client) -> tuple[ResumeDocument, dict | None, dict | None]:
    """Raises ResumeParseError, FetchError, OSError, ValueError or JSONDecodeError."""
    document = inspect_resume(arguments.resume)
    profile = load_profile(arguments.profile)
    job = read_job(arguments, client) if arguments.url or arguments.text_file else None
    return document, job, profile


def _data_dir(arguments: argparse.Namespace, document: ResumeDocument) -> Path:
    return choose_data_dir(arguments, {"synthetic": SYNTHETIC_MARKER in document.text.upper()})


def run_plan(arguments, document, job, profile) -> int:
    plan = build_plan(document, job, profile)
    write_json(_data_dir(arguments, document) / PLAN_FILE, plan)
    if arguments.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    print(f"ATS Readiness now: {plan['ats']['ats_score']}/100"
          + (f"   Job Match: {plan['job_match']['match_score']}/100" if plan["job_match"] else ""))
    for label, key in (("Put first", "emphasise"), ("Do not add (not shown anywhere you have used them)", "do_not_add"),
                       ("Your profile shows these; the resume should too", "supported_not_shown")):
        if plan[key]:
            print(f"\n{label}: {', '.join(plan[key])}")
    if plan["use_job_wording"]:
        print("\nUse the listing's words: " + ", ".join(f'"{item["job_term"]}" for "{item["resume_term"]}"'
                                                       for item in plan["use_job_wording"]))
    if plan["bullets_to_strengthen"]:
        print(f"\n{len(plan['bullets_to_strengthen'])} bullet(s) to strengthen; filler to remove: "
              f"{', '.join(plan['filler_to_remove']) or 'none'}")
    if plan["additional_information_required"]:
        print("\nAdditional information required:")
        print("\n".join(f"  - {item}" for item in plan["additional_information_required"]))
    print(f"\nFull plan: {_data_dir(arguments, document) / PLAN_FILE}")
    return 0


def run_draft(arguments, document, job) -> int:
    output = Path(arguments.output) if arguments.output else _data_dir(arguments, document) / DRAFT_FILE
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_draft(document, job), encoding="utf-8")
    print(f"Draft written to {output}. Wording is unchanged; only order, headings and grouping moved.")
    return 0


def run_verify(arguments, document, job, profile) -> int:
    rewritten = inspect_resume(arguments.optimized)
    result = verify(document, rewritten, job, candidate_skill_set(profile) if profile else set())
    write_json(_data_dir(arguments, document) / "optimization_check.json",
               {key: result[key] for key in ("passed", "unsupported_claims", "dropped_facts", "structure_problems",
                                             "comparison")})
    print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.json else format_verification(result))
    return VERIFIED_EXIT_CODE if result["passed"] else REJECTED_EXIT_CODE


def run(arguments: argparse.Namespace, client=None) -> int:
    if arguments.command == "export":
        try:
            markdown = Path(arguments.optimized).read_text(encoding="utf-8")
        except OSError as error:
            print(f"Could not read {arguments.optimized}: {error}", file=sys.stderr)
            return 2
        export_docx(markdown, Path(arguments.output))
        print(f"Wrote {arguments.output}")
        return 0
    try:
        document, job, profile = _load_inputs(arguments, client)
        if arguments.command == "plan":
            return run_plan(arguments, document, job, profile)
        if arguments.command == "draft":
            return run_draft(arguments, document, job)
        return run_verify(arguments, document, job, profile)
    except ResumeParseError as error:
        print(f"Could not read a resume: {error}", file=sys.stderr)
        return 2
    except FetchError as error:
        print(f"Could not read that job: {error}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"Could not read the profile: {error}. Pass a candidate_profile.json, not a resume.", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"Could not read an input file: {error}", file=sys.stderr)
        return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
