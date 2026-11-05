# Job search agent

Eight Claude skills that find real, open jobs for your resume, tell you how well each one
fits, and make your resume readable by screening software without inventing anything. Free,
MIT, no signup, no API key.

Give Claude your resume. It works out the roles you are realistically suited for, searches
company job boards, job portals and company career websites for open listings, throws out
the irrelevant ones and the duplicates, and scores every remaining job from 0 to 100. Each
score comes with its breakdown: the skills you match, the ones you are missing, and any hard
requirement you do not meet, such as "7+ years" or "must live in Germany".

**It never applies for you.** It finds and explains. You decide and you apply.

## Install

Paste this into Claude Code:

```
https://github.com/khairnarkalpesh/job-search-agent

Install this plugin, then run /job-profile on my resume.
```

Or as a plugin, yourself:

```
/plugin marketplace add khairnarkalpesh/job-search-agent
/plugin install job-search-agent@job-search-agent
```

Or copy the skills in by hand:

```bash
git clone https://github.com/khairnarkalpesh/job-search-agent.git
cp -r job-search-agent/skills/job-* ~/.claude/skills/
```

The first run installs three Python packages (`PyYAML`, `pypdf`, `python-docx`). Python 3.11
or newer is needed.

**In the Claude app** (claude.ai or desktop): zip each folder under `skills/` and upload it in
**Settings → Capabilities → Skills**, `job-search` first, since the others use its engine.
Code execution must be on, and its network access must allow the job sites (or all
domains), or every search comes back empty. Saved results do not carry over between chats
there.

## The eight

| Command | What it does |
| --- | --- |
| `/job-profile` | Your resume into a reviewed profile: years, seniority, skills with evidence, and the roles you fit. Saves your preferences. |
| `/job-search` | The full search across every source, ranked, with the reasons and the gaps for the top matches. |
| `/job-match` | One job, scored: a link, or text you paste from LinkedIn, Naukri, Indeed or a job alert email. |
| `/job-companies` | A watch list of companies checked on every search. Give it a careers page and it finds the hiring system behind it. |
| `/job-gaps` | The skills you are missing, ranked by how many of your matching jobs ask for them. |
| `/resume-ats` | ATS Readiness: whether screening software can parse your resume file, generally or for one job, with the fixes in order. |
| `/resume-optimize` | Your resume targeted at a job, then fact-checked: nothing added that your resume does not say, nothing lost. Before and after scores. |
| `/job-tracker` | The jobs you applied to: applied, interviewing, offer or rejected, with dates and notes, and a nudge when one has gone quiet for two weeks. |

A typical first session: `/job-profile` with your resume, then `/job-search`, then
`/job-match` on anything you found elsewhere. Before applying, `/resume-ats` on your resume
with that job, and `/resume-optimize` if it finds fixable weaknesses. Run `/job-search`
again a week later and it marks which jobs are new.

**Three scores, kept apart.** ATS Readiness asks whether the resume can be read. Job Match
asks whether you fit the job. The skill gap asks what is missing across all your jobs. They
measure different things and are never added together.

## Where the jobs come from

| Kind | Sources |
| --- | --- |
| Company job boards | Greenhouse, Lever, Ashby, Workable, SmartRecruiters |
| Job portals | Remotive, Remote OK, Himalayas, Arbeitnow |
| Company websites | Any careers page that publishes standard job data, or links to one of the boards above |
| Anything else | Paste it into `/job-match` |

All of these are public listings read through public APIs or public pages, with
`robots.txt` respected. Claude's web search finds which companies are hiring for your roles;
nothing is hard-coded.

## The fine print

**No LinkedIn, Indeed, Naukri or Glassdoor scraping.** Their terms forbid automated access
and they block it. Copy a listing from there into `/job-match` and it is scored like any other.

**Workday, Taleo, iCIMS and similar systems are not covered** unless the company's careers
page publishes standard job data. They have no public feed.

**The score is a guide, not a verdict.** It is rule-based and repeatable, and Claude
re-reads the top listings to catch what the rules misread. Read the gaps before you apply.

**Nothing is invented.** A salary, a remote policy or a requirement the listing does not
state stays unknown. Every job shown links to its original listing and names its source.
A rewritten resume is checked against your original, and any added skill, number, title,
employer, date, certification or degree is rejected.

**ATS Readiness is a heuristic, not a guarantee.** No tool can reproduce a particular
employer's screening system. It explains each point it gives or takes away.

**Your data stays on your machine**, in `~/.job-search-agent/`. Search queries sent to the
web use only job titles, skills and a country, never your name or contact details.

## More

- [docs/GUIDE.md](docs/GUIDE.md): every skill, flag and source in detail, how scoring works,
  and troubleshooting.
- Tests: `pip install -r requirements-dev.txt`, then `pytest` (offline) or `pytest -m live`
  (calls the real APIs).

## Licence

MIT. Use it, change it, ship it.
