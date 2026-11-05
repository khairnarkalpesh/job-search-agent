---
name: job-tracker
description: >-
  Track the jobs the user applies to - saved, applied, interviewing, offer,
  rejected or withdrawn - with dates, notes and the match score, and flag
  applications with no news for two weeks. Use for "I applied to this job",
  "mark Acme as interviewing", "I got rejected by X", "show my applications",
  "which jobs did I apply to", or "what should I follow up on".
---

# job-tracker

Run commands from `../job-search` (the folder beside this one). Applications live in
`~/.job-search-agent/data/applications.json`.

```bash
python scripts/applications.py list [--status interviewing]
python scripts/applications.py add "<job url or id>" [--status applied] [--date YYYY-MM-DD] [--note "..."]
python scripts/applications.py add "<job url>" --title "<title>" --company "<company>"
python scripts/applications.py update "<job url, id or company>" --status interviewing --note "Round 1 Friday"
python scripts/applications.py remove "<job url, id or company>"
```

Statuses: `saved`, `applied`, `interviewing`, `offer`, `rejected`, `withdrawn`. `add`
defaults to `applied` today.

A job already scored by `/job-search` or `/job-match` is found by its URL or id, and its
title, company and match score come from there. The status is also written to the search
history, so later searches keep it. For any other job (one seen on LinkedIn, say), pass
`--title` and `--company`; ask the user for them rather than guessing.

`update` and `remove` also accept the company or the title when only one tracked job
matches; when several do, the script says so, and you use the URL.

## Dates

Use the date the user gives ("I applied last Monday" → work out the date and pass
`--date`). Without one, today is used. Never invent a date for an event the user did not
describe.

## Reading the list

Open applications come first. "(follow up?)" marks one applied or interviewing with no
update for 14 days; offer a short, polite follow-up note if the user wants one. Do not
contact anyone on the user's behalf.
