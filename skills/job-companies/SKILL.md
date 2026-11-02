---
name: job-companies
description: >-
  Keep a watch list of companies that every job search checks - by careers page,
  job board URL or source:slug - and detect which hiring system a company's
  careers website runs on. Use for "watch these companies", "add Stripe",
  "search only my target companies", "which companies am I tracking", or a list
  of companies or careers URLs.
---

# job-companies

Run commands from `../job-search` (the folder beside this one). Saved companies live in
`~/.job-search-agent/data/known_boards.json` and are searched on every `/job-search`.

```bash
python scripts/companies.py list
python scripts/companies.py add https://careers.acme.com lever:globex https://jobs.ashbyhq.com/initech
python scripts/companies.py remove lever:globex
```

`add` fetches each one to confirm it works and prints how many listings are open. A
careers website is checked for a link to Greenhouse, Lever, Ashby, Workable or
SmartRecruiters; if one is found, that board is saved instead, since its API gives
complete listings.

## When the user gives company names, not URLs

Find each company's careers page with web search (query: `<company> careers`), then pass
the page URL or a job URL to `add`. Do not guess a board name: a wrong slug can match a
different company. Report any company you could not place.

## When the site could not be reached

`add` says so and does not blame the board name, because the name was never checked. If
the user is sure of the board (it came from a real job URL), offer to save it with
`--no-check`; the next `/job-search` checks it. Never use `--no-check` on a guessed slug.

## When a careers page has nothing machine-readable

`add` says so. The site loads jobs with JavaScript or uses a system without a public feed
(Workday, Taleo, iCIMS and others). Tell the user, and offer `/job-match` on single jobs
they open themselves.

Then offer `/job-search` (or `/job-search` with `--source` set to only company boards when
the user wants just their list).
