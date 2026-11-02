---
name: job-profile
description: >-
  Read a resume (PDF, DOCX, TXT or Markdown) into a reviewed candidate profile -
  years of experience, seniority, skills with evidence, and realistic target roles -
  and save job-search preferences. Use for "read my resume", "here is my CV",
  "update my profile", "I only want remote jobs", or before a first /job-search.
---

# job-profile

Every other `job-*` skill scores against the profile this one saves. Run commands from
`../job-search` (the folder beside this one), after
`python -m pip install -r requirements.txt` on first use (`python3` on macOS/Linux).

## 1. Draft

```bash
python scripts/search_jobs.py --resume "<path to resume>" --extract-only
```

This writes a rule-based draft to `~/.job-search-agent/data/candidate_profile.json`. A
scanned PDF has no text layer; ask for a DOCX or text copy.

## 2. Review

Read the resume yourself and correct the draft, following
[../job-search/prompts/resume-extraction.md](../job-search/prompts/resume-extraction.md).
The shape is in `../job-search/schemas/candidate-profile.schema.json`. In short:

- The resume is the only source. Leave out what it does not say.
- Keep out email, phone, street address, ID numbers, date of birth and profile links.
  Location stays at city and country.
- Every target role needs a `family` from `config/taxonomy.yaml` and a stated reason.
  No aspirational roles the resume cannot support. The first roles should follow the most
  recent job title and the summary, not a skill seen once in a college project.
- `skills_learning` lists skills the resume marks "(learning)", "basic" or "exposure"; they
  are not counted as skills. Keep it that way unless the resume shows real use elsewhere.
- `unrecognized_skills` lists Skills-section items the taxonomy does not know, so no job
  can match them. Mention them to the user; if one matters, it can be added to
  `config/taxonomy.yaml`.
- When the profile is right, set `"reviewed": true`. Until then every other skill warns
  that it is scoring against an unchecked draft.

## 3. Show the user

A short summary: years, seniority, top skills, target roles, and anything inferred at low
confidence. Ask a question only if the answer would change the search.

## 4. Preferences, only if the user states them

```bash
python scripts/search_jobs.py --extract-only --save-preferences --location "Remote,Pune" --role "Backend Engineer" --min-score 70 --remote
```

Or edit `~/.job-search-agent/preferences.yaml` (see `config/preferences.example.yaml`):
locations, roles, minimum score, sources, employment types, work authorisation, remote
preference. Never fill one in from where someone lives or what you guess they want.

Then offer `/job-search`, and `/resume-ats` on the same file to see whether screening
software can read it.
