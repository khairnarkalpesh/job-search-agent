---
name: job-match
description: >-
  Score one job against the saved resume profile, from its URL (Greenhouse,
  Lever, Ashby, Workable, SmartRecruiters or a company careers page) or from
  listing text the user pastes - including LinkedIn, Naukri, Indeed or a job
  alert email. Use for "does this job fit me", "score this job", "should I apply",
  a pasted job description, or a single job link.
---

# job-match

One job, scored the same way as `/job-search`, with the breakdown and the gaps. Run
commands from `../job-search` (the folder beside this one). Needs a saved profile; if
there is none, run `/job-profile` first.

## From a URL

```bash
python scripts/match_job.py --url "<job url>"
```

Works for any job on the supported boards, and for career pages that publish standard
job data. If it reports the job is not found, the posting has probably closed.

## From pasted text

For LinkedIn, Naukri, Indeed, Glassdoor, a recruiter email or any page the script cannot
read. Never fetch or scrape those sites; work only from text the user gives you.

1. Save the text exactly as given to `~/.job-search-agent/data/pasted_job.txt`.
2. Run:

```bash
python scripts/match_job.py --text-file ~/.job-search-agent/data/pasted_job.txt --source-name "LinkedIn"
```

The title is the first line, and company and location are read from labelled lines
("Location: Pune") or LinkedIn's "Company · Location" line. Check them in the output; if one
is wrong or missing and the text states it, pass `--title`, `--company` or `--location`.
Never fill one in that the text does not state.

Every job scored here is kept in `matched_jobs.json`, so `/job-gaps` counts it too.

If a company careers page loads its jobs with JavaScript, the script finds nothing. You
may read the page with your own web fetch tool and save the job text, as above.

## Then

Check the score against the listing with
[../job-search/prompts/job-matching.md](../job-search/prompts/job-matching.md): hard
requirements read from a "preferred" list, "Java or Go" read as both, and location limits
written only in the body. Never raise a score the resume does not support; state any
correction beside the number.

Answer with the score, the two or three strongest reasons, the real gaps, and a plain
recommendation (apply, apply and address a gap in the cover letter, or skip). Never suggest
misrepresenting experience.

## With the resume file

Add `--resume "<resume file>"` to either command to print ATS Readiness for this job beside
the match: whether the resume, as written, shows the listing's skills in a form screening
software can read. Present the three numbers separately: Job Match (fit), ATS Readiness
(readability for this job) and the job's missing required skills. Never add them up. If the
fit is good and ATS Readiness is low, offer `/resume-optimize`; for detail, `/resume-ats`.
