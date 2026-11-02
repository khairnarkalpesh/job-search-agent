# Resume extraction review

`search_jobs.py --extract-only` writes a rule-based draft to `~/.job-search-agent/data/candidate_profile.json`.
Read the resume yourself, compare it with the draft, and correct the file. The shape is
defined by `schemas/candidate-profile.schema.json`.

## Rules

1. The resume is the only source. If something is not in it, leave the field empty or null.
2. Keep out email, phone numbers, street addresses, ID numbers, dates of birth and profile
   links. The location stays at city and country level.
3. Keep every `evidence` entry accurate:
   - `explicit`: the resume says it. Quote or name the section.
   - `inferred`: you concluded it. Say from what, and set `confidence` to high, medium or low.
4. Add to `experience[].technologies` only what that job's text shows.
5. Use the taxonomy's skill names from `config/taxonomy.yaml` where one exists, because
   scoring compares those names. A skill with no taxonomy entry can stay under its own name.
6. `years_of_experience` is total professional experience. Do not count education, and count
   overlapping jobs once. If the resume's own statement disagrees with its dates, use the
   dates and record the disagreement in `evidence`.
7. `preferred_locations` and `remote_preference` come from the user or the resume only. Never
   infer a preference from where someone lives.

## Target roles

Each `target_roles` entry needs `title`, `family`, `role_relevance` (0 to 1), `confidence`
and `reason`. Remove any role the draft got wrong, and add a realistic one if the resume
clearly supports it. Do not add unrelated roles or aspirational roles the resume cannot
support. `family` must be a key under `role_families` in the taxonomy.

## Before moving on

Show the user a short summary: inferred years, seniority, top skills and target roles, with
anything inferred at low confidence called out. Only ask a question if the answer would
change the search.
