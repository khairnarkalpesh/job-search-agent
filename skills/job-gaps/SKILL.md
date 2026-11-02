---
name: job-gaps
description: >-
  Rank the skills missing from a resume by how many matching jobs ask for them,
  using saved job search results - required skills weighed above mentions. Use
  for "what should I learn", "what skills am I missing", "why are my scores low",
  "skill gap", or after a /job-search with many near misses.
---

# job-gaps

Run from `../job-search` (the folder beside this one) after at least one `/job-search` or a
few `/job-match` runs: jobs scored either way are counted.

```bash
python scripts/skill_gaps.py [--min-score 40] [--top 10]
```

It counts only jobs that were scored reliably and that score at least `--min-score`, so
the answer reflects roles the user is close to, not every listing seen. A skill a job
requires counts three times as much as one it only mentions.

## Answer

- The top three or four gaps, each with how many jobs require it.
- Which of them are close to what the resume already shows (a related skill in
  `config/taxonomy.yaml`), because those are the quickest to close.
- One concrete next step for the biggest gap. Do not recommend claiming a skill the user
  does not have.

If fewer than ten jobs were counted, say the sample is small and suggest a wider
`/job-search` first.
