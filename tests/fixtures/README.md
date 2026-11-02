# Test fixtures

- `recorded_*.json`: real responses from the public APIs of Greenhouse, Lever, Ashby,
  Workable, SmartRecruiters, Remotive, Remote OK, Himalayas and Arbeitnow, trimmed to a few
  jobs, with recruiter names removed. They may go stale, which is fine: they only test parsing.
- `recorded_duckduckgo_block_page.html`: the real bot-check page, used to test that a block
  stops the search.
- `synthetic_resume.*`: invented person, labelled as synthetic on its first line. The tool
  sees the label and keeps results apart from real data.
