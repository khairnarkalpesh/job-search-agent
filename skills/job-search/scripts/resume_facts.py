"""The facts a resume states, and a check that a rewritten resume states no others.

A rewrite may reorder, reword and drop filler. It may not add an employer, a title, a
date, a skill, a figure, a certification or an education detail the original does not
contain, and it may not lose one the original does. Both checks are deliberately
literal: a false alarm costs a second look, a missed invention costs the candidate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from hard_requirements import CERTIFICATION
from resume_outline import lines_meaning, outline
from resume_parser import DATE_RANGE, group_experience, remove_contact_details
from skill_taxonomy import find_skills

_FIGURE = re.compile(r"\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[a-z0-9][a-z0-9+#.]*")
# Words a reworded education or certification line can gain without adding a claim.
_CONNECTING_WORDS = {"in", "of", "and", "the", "with", "at", "from", "for", "a", "an", "to", "on", "degree"}


def normalise(text: str) -> str:
    text = re.sub(r"\s*[–—-]\s*", " - ", text.lower())
    return re.sub(r"\s+", " ", text).strip(" ,.;:|()")


def _words(text: str) -> set[str]:
    return {word.rstrip(".") for word in _WORD.findall(text.lower())}


@dataclass
class ResumeFacts:
    employers: list[str]
    titles: list[str]
    date_ranges: list[str]
    skills: list[str]
    figures: set[str]
    education: list[str]
    certifications: list[str]
    named_certifications: set[str]
    words: set[str]

    @classmethod
    def of(cls, text: str) -> ResumeFacts:
        sections = outline(text)
        blocks = group_experience(lines_meaning(sections, "experience"))[1]
        return cls(
            employers=[block.company for block in blocks if block.company],
            titles=[block.role for block in blocks if block.role],
            date_ranges=[normalise(match.group(0)) for match in DATE_RANGE.finditer(text)],
            skills=find_skills(text),
            figures=set(_FIGURE.findall(remove_contact_details(text))),  # a phone number is not a claim
            education=lines_meaning(sections, "education"),
            certifications=lines_meaning(sections, "certifications"),
            named_certifications={normalise(match.group(0)) for match in CERTIFICATION.finditer(text)},
            words=_words(text),
        )

    def to_dict(self) -> dict:
        return {"employers": self.employers, "titles": self.titles, "date_ranges": self.date_ranges,
                "skills": self.skills, "figures": sorted(self.figures), "education": self.education,
                "certifications": self.certifications}


def _known(value: str, originals: list[str]) -> bool:
    """A name counts as known when it matches, or is contained in, one the original states."""
    wanted = normalise(value)
    return any(wanted == normalise(known) or wanted in normalise(known) or normalise(known) in wanted
               for known in originals)


def _claim(kind: str, value: str, reason: str) -> dict:
    return {"kind": kind, "value": value, "reason": reason}


def unsupported_claims(original: ResumeFacts, rewritten: ResumeFacts, evidence_skills: set[str]) -> list[dict]:
    """What the rewrite states that the original resume, or the reviewed profile, does not."""
    claims = [_claim("skill", skill, "not in the original resume or your profile")
              for skill in rewritten.skills if skill not in original.skills and skill not in evidence_skills]
    claims += [_claim("employer", employer, "employer not in the original resume")
               for employer in rewritten.employers if not _known(employer, original.employers)]
    claims += [_claim("title", title, "job title not in the original resume")
               for title in rewritten.titles if not _known(title, original.titles)]
    claims += [_claim("dates", dates, "date range not in the original resume")
               for dates in rewritten.date_ranges if dates not in original.date_ranges]
    claims += [_claim("figure", figure, "number not in the original resume; figures are never estimated")
               for figure in sorted(_claimed_figures(rewritten) - original.figures)]
    claims += [_claim("certification", name, "certification not in the original resume")
               for name in sorted(rewritten.named_certifications - original.named_certifications)]
    for kind, lines in (("education", rewritten.education), ("certification", rewritten.certifications)):
        for line in lines:
            new_words = _words(line) - original.words - _CONNECTING_WORDS
            if new_words:
                claims.append(_claim(kind, line, f"adds {', '.join(sorted(new_words))}"))
    return claims


def dropped_facts(original: ResumeFacts, rewritten: ResumeFacts) -> list[dict]:
    """What the original resume states that the rewrite lost."""
    dropped = [_claim("employer", employer, "employer missing from the rewrite")
               for employer in original.employers if not _known(employer, rewritten.employers)]
    dropped += [_claim("title", title, "job title missing from the rewrite")
                for title in original.titles if not _known(title, rewritten.titles)]
    dropped += [_claim("dates", dates, "date range missing from the rewrite")
                for dates in original.date_ranges if dates not in rewritten.date_ranges]
    dropped += [_claim("figure", figure, "number missing from the rewrite; keep every real figure")
                for figure in sorted(_claimed_figures(original) - rewritten.figures)]
    for kind, lines in (("education", original.education), ("certification", original.certifications)):
        for line in lines:
            lost_words = _words(line) - rewritten.words - _CONNECTING_WORDS
            if lost_words:
                dropped.append(_claim(kind, line, f"missing from the rewrite: {', '.join(sorted(lost_words))}"))
    return dropped


def _claimed_figures(facts: ResumeFacts) -> set[str]:
    """Figures, less the years of date ranges: a moved date is reported once, as dates."""
    years = {year for dates in facts.date_ranges for year in re.findall(r"\b(?:19|20)\d{2}\b", dates)}
    return facts.figures - years
