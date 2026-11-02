# Job search agent: the guide

Everything the seven skills do, every option they take, and what to do when something goes
wrong. For a quick start, see the [README](../README.md).

- [How the pieces fit](#how-the-pieces-fit)
- [/job-profile](#job-profile): read your resume
- [/job-search](#job-search): find and rank jobs
- [/job-match](#job-match): score one job
- [/job-companies](#job-companies): your company watch list
- [/job-gaps](#job-gaps): what to learn next
- [/resume-ats](#resume-ats): can screening software read your resume
- [/resume-optimize](#resume-optimize): target your resume at a job, truthfully
- [Three separate scores](#three-separate-scores)
- [Sources](#sources)
- [How a score is worked out](#how-a-score-is-worked-out)
- [How ATS Readiness is worked out](#how-ats-readiness-is-worked-out)
- [Your data](#your-data)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)

## How the pieces fit

You talk to Claude; Claude runs the skills. You never have to type a command yourself,
though every command below also works on its own in a terminal.

```
resume ──/job-profile──▶ profile ──/job-search──▶ ranked jobs ──/job-gaps──▶ skills to learn
                            │
                            ├──/job-match──▶ one job, scored (link or pasted text)
                            └──/job-companies──▶ companies checked on every search

resume file ──/resume-ats──▶ ATS Readiness (general, or for one job)
resume file + job ──/resume-optimize──▶ targeted resume ──verify──▶ before/after ATS Readiness
```

`/job-profile` comes first: every other skill scores against the profile it saves.

All the code lives in `skills/job-search/`. The other six skills are short instructions
that call its scripts, so keep the `skills/` folders side by side when you install.

You can ask in plain words instead of typing a command. "Here's my CV, find me backend jobs
in Pune or remote" runs `/job-profile` and then `/job-search` with those filters.

## /job-profile

**Ask:** "Read my resume at `C:\Users\me\resume.pdf`", or attach the file.

1. The script reads the resume (PDF, DOCX, TXT or Markdown) and writes a draft profile:
   total years of experience, seniority, skills grouped by kind, each job's technologies,
   and target roles, each with a reason and a confidence level.
2. Claude reads the resume itself and corrects the draft. It removes a skill you only
   mention as "learning", for example, or a role your experience does not support.
3. Claude shows you a summary and points out anything it was unsure of.

Contact details, addresses and profile links are never stored. Location is kept at city and
country level.

**Preferences.** Tell Claude what you want ("remote or Pune only, minimum score 70, full time")
and it saves those preferences. You can also edit `~/.job-search-agent/preferences.yaml`
directly:

| Preference | Example |
| --- | --- |
| `target_locations` | `[Remote, Pune, Bangalore]` |
| `target_roles` | `[Backend Engineer]` |
| `minimum_match_score` | `70` |
| `preferred_sources` | `[greenhouse, lever, ashby, remotive]` |
| `employment_types` | `[full_time]` |
| `work_authorization` | `[India]` |
| `remote_preference` | `remote_only`, `hybrid_ok` or `onsite_ok` |

An empty preference means "use what the resume says". Nothing is filled in for you.

**Terminal:**

```bash
cd skills/job-search
python scripts/search_jobs.py --resume resume.pdf --extract-only
python scripts/search_jobs.py --extract-only --save-preferences --location "Remote,Pune" --min-score 70
```

## /job-search

**Ask:** "Find me jobs", "Any new backend jobs this week?", or "Search only remote roles,
score 75 and up".

What happens:

1. **Plan.** Search queries are built from your target roles, top skills and country.
2. **Discover.** Claude runs those queries with its web search to find companies hiring on
   Greenhouse, Lever, Ashby, Workable and SmartRecruiters. Boards found on earlier runs or
   added with `/job-companies` are reused.
3. **Fetch.** Every open listing is read from each board, and the job portals are searched
   for your target roles.
4. **Filter.** Listings for unrelated roles (sales, mechanical engineering, management), in
   the wrong place, or of the wrong employment type are dropped. A job posted on more than
   one site is kept once.
5. **Score.** Every remaining job gets a 0-100 score with its breakdown.
6. **Review.** Claude re-reads the top listings to catch what the rules misread. A
   "7+ years" line that is really in the nice-to-have list is one example.
7. **Report.** You get a table, a detailed breakdown of the top five, and a link to every
   original listing.

A typical run reads 10 to 30 boards and 1,000 to 2,000 listings and ends with 100 to 300
scored jobs. Expect a few minutes.

**Options** (say them in words, or pass them in a terminal):

| Option | Effect |
| --- | --- |
| `--location "Remote,Bangalore"` | Only jobs that fit these places |
| `--remote` | Remote only. Hybrid does not count as remote |
| `--role "Data Engineer"` | Only this kind of role |
| `--min-score 75` | Hide jobs below 75 (default 60, or your saved preference) |
| `--all` | Show every scored job, whatever its score |
| `--limit 30` | Show up to 30 (default 20) |
| `--new-only` | Only jobs that were not found on earlier runs |
| `--source ashby,lever,remotive` | Use only these sources (default: all) |
| `--board greenhouse:acme` | Also read this company's board; repeatable |
| `--urls-file urls.txt` | Read boards from a list of job or board URLs |
| `--plan` | Print the web search queries and stop |
| `--save-preferences` | Remember this run's filters |

**Terminal** (without Claude, discovery uses DuckDuckGo, which often blocks automated
searches; pass `--board` or `--urls-file` if it does):

```bash
python scripts/search_jobs.py --location "Remote,Pune" --limit 20
python scripts/search_jobs.py --board ashby:acme --board lever:globex --source ashby,lever --all
```

**Output** for each job: score and band (Excellent 90+, Strong 80+, Good 70+, Possible 60+,
Low), the score breakdown, why it matches, the potential gaps, the source and link, and
whether it is a `NEW JOB` or `PREVIOUSLY SEEN`.

## /job-match

**Ask:** "Does this fit me? `<link>`", or paste a whole job description.

- **A link** to a job on any supported board, or on a careers page with standard job data,
  is fetched and scored.
- **Pasted text** works for anything, including LinkedIn, Naukri, Indeed, Glassdoor or a
  recruiter's email. Claude saves your text and scores it. It never visits those sites.

The answer gives the score with its breakdown, the main reasons, the real gaps, and a
recommendation: apply, apply and address a gap in your cover letter, or skip.

```bash
python scripts/match_job.py --url https://jobs.lever.co/acme/1234-abcd
python scripts/match_job.py --text-file job.txt --title "Backend Engineer" --company Acme --location "Pune, India" --source-name LinkedIn
python scripts/match_job.py --url ... --json      # the full scored record
```

## /job-companies

**Ask:** "Watch Stripe, Razorpay and Postman", "Add https://careers.acme.com", or "Which
companies am I tracking?"

Saved companies are checked on every `/job-search`, even when web search finds nothing new.
Give a careers page and the skill looks for the hiring system behind it. If it finds one, it
saves that board, which gives complete and up-to-date listings. Each one is fetched when
added, so you see straight away how many jobs are open.

```bash
python scripts/companies.py list
python scripts/companies.py add https://careers.acme.com lever:globex https://jobs.ashbyhq.com/initech
python scripts/companies.py remove lever:globex
```

From company names alone, Claude finds each careers page with web search first. It never
guesses a board name, because a wrong one can belong to a different company.

## /job-gaps

**Ask:** "What skills am I missing?" or "What should I learn to get more of these jobs?"

Counts the skills missing from your resume across your saved results. Only jobs that were
scored reliably and score at least 40 are counted. A skill a job requires counts three
times as much as one it only mentions. Claude then points out which gaps are close to
something you already know, and suggests one concrete next step.

```bash
python scripts/skill_gaps.py --min-score 50 --top 15
```

## /resume-ats

**Ask:** "Is my resume ATS friendly?", "Check my CV for this job: `<link>`", or attach the
file with a pasted listing.

ATS Readiness answers one question: **can this resume be parsed and understood by
screening software?** It reads the file itself, because layout is part of the answer. It
checks whether a parser can pull out your name, contact details, job titles, employers and
dates; whether the sections are standard and in a sensible order; whether the bullets, skills
list and summary say something checkable; and whether tables, columns, text boxes, page
headers, images, icons or hidden text could lose or scramble anything.

Given a job, it also checks keyword coverage (the listing's skills, in the listing's words)
and required skills, sorts the listing into required, preferred, responsibilities,
technology, experience, education, location and seniority, and prints Job Match beside it.

The answer is a score out of 100 with each category's points, the strengths, the issues and
the fixes in order of points at stake. Skills the listing wants and your resume does not show
are never suggested as keywords to add: they go under **Additional information required**, as
questions. If your saved profile shows the skill, it is suggested, since naming it is true.

```bash
python scripts/resume_ats.py --resume resume.pdf
python scripts/resume_ats.py --resume resume.docx --url https://jobs.lever.co/acme/1234-abcd
python scripts/resume_ats.py --resume resume.docx --text-file job.txt --title "Backend Engineer"
python scripts/match_job.py --url ... --resume resume.docx   # Job Match and ATS Readiness together
```

**Limits.** This is a heuristic with its reasons shown. It does not and cannot reproduce any
vendor's screening algorithm, and no score here is a guarantee. Keywords are the skills in
`config/taxonomy.yaml`, so a listing term the taxonomy does not know is not counted. Two
columns in a PDF are guessed from text positions, and the report says it is a guess. Contact
details are checked for presence only and never stored.

## /resume-optimize

**Ask:** "Tailor my resume to this job", or "Fix what /resume-ats found".

1. **Plan.** The ATS report, the Job Match score, the facts the rewrite must keep to, which of
   your skills to put first, the listing's wording for skills you already show, the listing's
   skills **not** to add, weak bullets, filler, headings to rename, and questions for you.
2. **Draft.** A safe first version, written by the script: standard headings, skills grouped
   with the job's first, the most relevant bullets and projects first, filler removed. Every
   line comes from your resume.
3. **Rewrite.** Claude improves the summary and the bullets, following
   `prompts/resume-optimization.md`: action verbs, clearer wording, the listing's terms where
   they describe what you did.
4. **Verify.** The script compares the rewrite with your original and rejects it if it adds or
   loses any employer, job title, date, skill, number, certification or education detail. Only
   then does it show ATS Readiness before and after.
5. **Export.** A single-column Word file, if you want one.

```bash
python scripts/resume_optimize.py plan   --resume resume.docx --url ...
python scripts/resume_optimize.py draft  --resume resume.docx --url ...
python scripts/resume_optimize.py verify --resume resume.docx --optimized ~/.job-search-agent/data/optimized_resume.md --url ...
python scripts/resume_optimize.py export --optimized ~/.job-search-agent/data/optimized_resume.md --output resume_for_acme.docx
```

**Nothing is invented.** No skill, metric, title, employer, date, project, certification or
qualification is added that your resume or reviewed profile does not state. "Improved
performance by 47%" is rejected unless 47% is in your original. A rewrite stuffed with the
listing's keywords would score higher, which is why `verify` refuses it (exit code 3) and the
after score does not count until it passes. If an improvement needs information you have not
given, it is asked for, not guessed. Give the answer and it goes into a copy of your original,
which the rewrite is then checked against.

The check is literal: it catches added facts, not a sentence that overstates a fact already
there ("helped with" becoming "led"). Claude is instructed against that, and you should still
read the result before sending it.

## Three separate scores

| Score | Answers | From |
| --- | --- | --- |
| ATS Readiness | Can this resume be parsed and understood? | `/resume-ats` |
| Job Match | How well do you fit this job? | `/job-match`, `/job-search` |
| Skill gap | Which skills are missing across the jobs you want? | `/job-gaps` |

They are never added together. A resume can read perfectly (ATS 95) for a job you do not fit
(Job Match 40), or describe a strong fit badly (Job Match 85, ATS 55). The first is a reason
to look elsewhere; the second is fixed with `/resume-optimize`. `/job-gaps` is about learning,
not wording, and its skills are never added to a resume.

## Sources

| Source | Kind | What it covers | How it is read |
| --- | --- | --- | --- |
| Greenhouse | Company board | Many tech companies | Public Job Board API |
| Lever | Company board | Many startups and scale-ups | Public Postings API |
| Ashby | Company board | Many startups and AI companies | Public Job Posting API |
| Workable | Company board | Small and mid-size companies worldwide | Public jobs widget feed |
| SmartRecruiters | Company board | Large employers (Bosch, Visa and others) | Public Posting API, plus one detail call per relevant job |
| Remotive | Job portal | Remote jobs, worldwide | Public API, searched by your roles |
| Remote OK | Job portal | Remote jobs, worldwide | Public API, by tag |
| Himalayas | Job portal | Remote jobs, worldwide | Public search API |
| Arbeitnow | Job portal | Jobs in Germany and the EU | Public feed of recent jobs |
| Company website | Careers page | Pages with schema.org JobPosting data, or linking to a board above | The page itself, with `robots.txt` respected |

**Not covered, on purpose:** LinkedIn, Indeed, Naukri, Glassdoor and Foundit, whose terms
forbid automated access. Use `/job-match` with pasted text for these.

**Not covered, for now:** Workday, Taleo, iCIMS, SuccessFactors and other systems without a
public feed. Careers pages that load jobs only with JavaScript are not covered either; Claude
can read a single job from one with its own web fetch and use `/job-match`.

**Portal terms.** Remotive, Remote OK and Arbeitnow ask that each job links back to them and
names them as the source. The report does both. Remotive also asks for no more than four
calls a day, so portal responses are cached for six hours.

## How a score is worked out

Seven parts, added up to 100:

| Part | Points | What it measures |
| --- | --- | --- |
| Skills | 30 | Each skill the listing names, weighted by whether it is required (full weight), preferred (half) or mentioned (quarter). An exact match earns full credit, a related skill 70%, a transferable one 40% |
| Experience | 20 | Your years against the years the listing asks for |
| Role | 15 | How close the job title is to your target roles |
| Qualifications | 15 | How many of the listing's stated requirements you meet |
| Technology | 10 | Databases, cloud and DevOps tools in common |
| Location | 5 | Whether the job's location or remote status fits yours |
| Seniority | 5 | Junior, mid, senior or staff, against your level |

**Caps.** A hard requirement you do not meet caps the score at 64: a years minimum well
above yours, a required degree or mandatory certification you do not list, a must-have
technology, work rights you have not listed, a required language, or a location limit. Two or more cap it at
49. This keeps one disqualifier from hiding behind an otherwise good match.

**Reliability.** A listing with under 300 characters of text, or naming fewer than three
skills, is scored but marked unreliable and left out of the top matches. One lucky match on
a near-empty listing would otherwise look perfect.

**Neutral parts.** When a listing says nothing about something, for example years of
experience, that part gets half marks, and the breakdown says so.

**Skill names** come from `skills/job-search/config/taxonomy.yaml`, which maps aliases
("k8s" is Kubernetes) and related skills ("Spring Boot" is close to "Spring"). Add a skill
there to have it recognised.

## How ATS Readiness is worked out

Six categories, added up to 100 when a job is given:

| Category | Points | What it measures |
| --- | --- | --- |
| Parsing readiness | 20 | Name, email, phone and location in the main text; a title, employer and dates for every job; Education and Skills readable. Present only in a page header or text box: 40% credit |
| Structure | 15 | Experience, Skills and Education present (Education, Skills and Projects for an early-career resume); standard headings; no repeated sections; contact details at the top; Experience before Education once you have two years of work |
| Keyword coverage | 25 | Each listing skill, weighted required 1, preferred 0.5, mentioned 0.25. Same words 100%, same skill in other words 80%, related skill 30%, transferable 10%. A word-matching parser does not know Kotlin is close to Java, so related skills earn less than in Job Match |
| Required skills | 20 | 15 for the listing's required skills, on the same credits; 5 for required years, degree, certifications and languages visible on the resume |
| Section quality | 10 | Bullets per job, action verbs, duty-style openers, technologies named in bullets, bullet length, any measured outcome; skills list length, grouping and whether listed skills appear in use; summary length, filler and focus. Keyword stuffing and hidden text cost points here |
| Formatting safety | 10 | Starts at 10. Layout tables -3 (small ones -1), declared columns -3 (guessed -2), text boxes -3, contact details in a page header -2, image-only pages -4, icon glyphs -1.5, garbled characters -2, other images, emoji and symbol lines -0.5 |

Without a job, Keyword coverage and Required skills are shown as not assessed and the other
55 points are scaled to 100; the report says so. A check that does not apply is left out and
the rest of its category is scaled, so a student is not marked down for having no jobs.

Fixes are listed by the points they would win back. A missing section caused by a home-made
heading ("Where I've Worked") gives one fix, the rename, not five. The words counted as
action verbs, duty openers and filler are in `config/resume_language.yaml`.

## Your data

Everything is kept on your machine, in `~/.job-search-agent/`
(`C:\Users\<you>\.job-search-agent\` on Windows):

| File | Holds |
| --- | --- |
| `data/candidate_profile.json` | Your reviewed profile |
| `data/job_results.json` | Every scored job, with its breakdown |
| `data/search_history.json` | When each job was first and last seen, and each run's summary |
| `data/known_boards.json` | Company boards found or added |
| `preferences.yaml` | Your saved preferences |
| `data/ats_report.json` | The last ATS Readiness report (which contact fields were found, never their values) |
| `data/optimization_plan.json` | The last `/resume-optimize` plan |
| `data/optimized_resume.md` | The last optimized resume |
| `data/optimization_check.json` | The last fact check, and the before and after scores |
| `cache/` | Portal responses, kept for six hours |

To keep it somewhere else, set `JOB_SEARCH_AGENT_HOME`. To start over, delete the folder.
Plugin updates never touch it.

Search queries contain job titles, skills and a country only. A resume marked as synthetic
on its first line, as the test resumes are, writes to `synthetic_run_output/`, apart from
real data.

## Troubleshooting

| You see | Do this |
| --- | --- |
| "Could not load your profile" | A scanned PDF has no text. Use a DOCX or text copy |
| "No target roles could be worked out" | Run `/job-profile` again, or name a role |
| "No job boards to search" | Let Claude run the web search, or add companies with `/job-companies` |
| "Web search unavailable" | DuckDuckGo blocked the terminal run. Run through Claude, or pass `--board` |
| "Skipped …: source unavailable (blocked)" | That board refused the request. The rest of the run is fine |
| "No jobs reached the minimum score" | It names the best score. Ask for `--all` or a lower minimum |
| "only N had enough information to score reliably" | Short listings. Normal, especially on portals |
| Every request fails in the Claude app | The code sandbox cannot reach the job sites. Allow network access for code execution in Settings, or use Claude Code |
| "REJECTED: the rewrite states things the original resume does not" | The rewrite added a skill, number, title or other fact. Remove it, or give the information and add it to a copy of your original |
| ATS Readiness differs between your PDF and DOCX | They really are read differently. Fix the risks listed for the file you send |
| Scores look wrong for a job | Ask Claude to review it. It re-reads the listing and notes corrections beside the score |

## For developers

```
.claude-plugin/        plugin.json and marketplace.json
skills/
  job-search/          the engine: scripts/, config/, prompts/, schemas/, SKILL.md
  job-profile/         SKILL.md
  job-match/           SKILL.md
  job-companies/       SKILL.md
  job-gaps/            SKILL.md
  resume-ats/          SKILL.md
  resume-optimize/     SKILL.md
tests/                 offline tests on recorded real API responses
docs/GUIDE.md          this file
```

**Tests.** `pip install -r requirements-dev.txt`, then `pytest` from the repo root. Tests use
recorded responses in `tests/fixtures/` and never touch your real data folder.
`pytest -m live` calls the real APIs, using boards saved by your last search.

**Adding a source.** Write a module in `skills/job-search/scripts/sources/` with a `Source`
subclass. Set `name`, `label` and `kind` (`ats`, `portal` or `website`), and implement
`parse_url` and `fetch_board`. Portals also implement `boards_for`, which turns role titles
into searches, and sources whose listings lack text implement `complete_job`. List it in
`sources/__init__.py`, add a recorded response to `tests/fixtures/`, and add tests beside
`tests/test_more_sources.py`. Only use APIs whose terms allow it.
