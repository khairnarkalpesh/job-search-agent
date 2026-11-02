"""Regression tests for the problems found when the plugin ran on a real resume and seven listings.

Each test names the problem it guards. Listings and resumes are synthetic reconstructions of
the reported cases, not the real ones.
"""
import json

import pytest

import match_job
import skill_gaps
from ats_readiness import assess_resume, format_separate_scores, overused_terms
from conftest import build_job
from hard_requirements import evaluate_hard_requirements, required_years
from job_discovery import build_search_queries
from job_storage import JobStore, profile_warning
from location_matching import candidate_targets, match_location
from normalize_jobs import closed_listing_reason
from resume_layout import ResumeDocument
from resume_optimize import build_draft, format_verification, structure_problems, verify
from resume_parser import build_profile, group_experience, group_projects, qualified_skills
from score_jobs import assess_job_skills, score_job
from skill_taxonomy import alternative_groups, find_skills
from sources.generic import unsupported_hiring_system

FILLER = "We build products for customers across India. " * 12


def importance(description, have=frozenset(), title="Frontend Engineer"):
    job = build_job(title=title, description=description + FILLER)
    return {item["skill"]: item for item in assess_job_skills(job, set(have))}


# Requirement levels -----------------------------------------------------------------------

def test_a_skill_in_responsibilities_and_nice_to_have_is_required():
    found = importance("Responsibilities\n- Build interfaces in Vue 3 and TypeScript\nRequirements\n"
                       "- 3+ years of frontend experience\nNice to have\n- Vue 3\n")
    assert found["Vue.js"]["importance"] == "required"


def test_a_key_skills_heading_lists_requirements():
    found = importance("Key Skills\n- Vue 3, TypeScript\nGood to have\n- Vue 3, Nuxt\n")
    assert found["Vue.js"]["importance"] == "required" and found["TypeScript"]["importance"] == "required"


def test_a_nice_to_have_heading_still_lists_preferences():
    found = importance("Requirements\n- React\nNice to have skills\n- GraphQL\n")
    assert found["GraphQL"]["importance"] == "preferred"


# Either-or lists --------------------------------------------------------------------------

@pytest.mark.parametrize("text, group", [
    ("Backend in Node.js, Python or PHP", ["Node.js", "Python", "PHP"]),
    ("GCP, AWS or Azure", ["GCP", "AWS", "Azure"]),
    ("Experience with AWS and/or GCP", ["AWS", "GCP"]),
    ("Java/Kotlin and Spring Boot", ["Java", "Kotlin"]),
])
def test_alternative_lists_are_recognised(text, group):
    assert group in alternative_groups(text)


@pytest.mark.parametrize("text", ["React and TypeScript", "React, TypeScript, Redux", "CI/CD with Docker"])
def test_lists_without_a_choice_are_not_alternatives(text):
    assert alternative_groups(text) == []


def test_one_option_of_an_or_list_meets_it():
    found = importance("Requirements\n- Backend in Node.js, Python or PHP\n- GCP, AWS or Azure\n", {"Node.js", "AWS"})
    assert found["Node.js"]["importance"] == "required" and found["AWS"]["importance"] == "required"
    assert {found[skill]["importance"] for skill in ("Python", "PHP", "GCP", "Azure")} == {"alternative"}


def test_an_or_list_with_no_option_held_is_one_gap_not_three(profile):
    job = build_job(description="Requirements\n- 3+ years of Java\n- Experience with Ruby, PHP or Swift\n" + FILLER)
    scored = score_job(job, profile)
    assert len([gap for gap in scored["gaps"] if "Ruby" in gap or "PHP" in gap or "Swift" in gap]) == 1
    assert "One of Ruby or PHP or Swift is required" in " ".join(scored["gaps"])
    assert scored["missing_required_skills"] == ["Ruby"]


def test_a_strict_or_requirement_is_met_by_one_option(profile):
    job = build_job(description="Requirements\n- Must have Java, Go or Rust\n" + FILLER)
    result = evaluate_hard_requirements(job, profile, {}, {"Java"}, match_location(job, ["Pune, India"]))
    assert not any(item["type"] == "technology" for item in result["hard_requirements_failed"])
    assert any("You have Java" in item["detail"] for item in result["hard_requirements_met"])


def test_a_related_skill_is_not_reported_as_held(profile):
    job = build_job(description="Requirements\n- Must have NestJS\n" + FILLER)
    result = evaluate_hard_requirements(job, profile, {}, {"Node.js"}, match_location(job, ["Pune, India"]))
    assert not any("You have" in item["detail"] for item in result["hard_requirements_met"])
    assert any("not the same" in item["detail"] for item in result["unknown_requirements"])


# Experience phrasing ----------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("Up to 4 years of experience in frontend", (0, 4)),
    ("Minimum 5 years in software development", (5, None)),
    ("At least 3 years of professional experience", (3, None)),
    ("3-6 years of experience", (3, 6)),
    ("Experience: 2 to 4 years", (2, 4)),
    ("5+ yrs experience with React", (5, None)),
])
def test_experience_phrasing(line, expected):
    assert required_years({"requirements": [line], "description": line, "preferred_qualifications": []})[:2] == expected


def test_up_to_four_years_does_not_count_against_five_years_held(profile):
    job = build_job(description="Requirements\n- Up to 4 years of experience with Java\n" + FILLER)
    scored = score_job(job, profile)
    assert not any(item["type"] == "experience" for item in scored["hard_requirements"]["hard_requirements_failed"])


def test_stated_years_set_the_level_not_the_title(profile):
    job = build_job(title="Senior Backend Engineer", description="Requirements\n- 3-6 years of experience with Java\n" + FILLER)
    detail = score_job(job, profile)["score_breakdown"]["seniority"]["detail"]
    assert "mid (3-6 years asked)" in detail


# Fundamentals -----------------------------------------------------------------------------

def test_a_fundamental_the_resume_does_not_name_is_unverified_not_missing(profile):
    job = build_job(description="Requirements\n- Java\n- Strong data structures and algorithms\n" + FILLER)
    scored = score_job(job, profile)
    assert scored["unverified_skills"] == ["Data Structures"]
    assert "Data Structures" not in scored["missing_skills"] + scored["missing_required_skills"]
    assert any(gap.startswith("Unverified: Data Structures") for gap in scored["gaps"])


# Resume parsing ---------------------------------------------------------------------------

def test_wrapped_bullet_lines_are_one_bullet():
    _, blocks = group_experience(["Frontend Engineer | Acme | Jan 2022 - Present",
                                  "- Built a React dashboard used by", "support teams across three regions",
                                  "- Wrote component tests"])
    assert blocks[0].body == ["Built a React dashboard used by support teams across three regions",
                              "Wrote component tests"]


def test_a_company_line_above_the_next_job_is_not_joined_to_a_bullet():
    _, blocks = group_experience(["Engineer | Acme | 2020 - 2022", "- Built things", "Globex",
                                  "Senior Engineer, 2022 - 2024", "- Led things"])
    assert blocks[0].body == ["Built things"] and blocks[1].company == "Globex"


def test_paragraph_style_jobs_are_left_line_by_line():
    _, blocks = group_experience(["Engineer | Acme | 2020 - 2022", "Built things.", "Ran things."])
    assert blocks[0].body == ["Built things.", "Ran things."]


def test_css_inside_longer_terms_is_not_counted_as_stuffing():
    text = ("Skills\nCSS3, Tailwind CSS, CSS Modules, HTML\n- Built pages with Tailwind CSS\n- Styled with CSS Modules\n"
            "- Wrote CSS3 animations\n- Migrated CSS to Tailwind CSS\n- CSS grid layouts\n" + FILLER * 2)
    assert overused_terms(text) == []
    assert find_skills("Tailwind CSS") == ["Tailwind CSS"]


def test_real_repetition_is_still_stuffing():
    assert overused_terms("Java " * 30)[0]["term"] == "Java"


def test_achievements_do_not_run_into_education():
    profile = build_profile("Asha Test\nPune, India\nEducation\nB.E. Computer, Example College, 2021\nACHIEVEMENTS\n"
                            "- 3rd place in a national coding contest\nSkills\nReact\n")
    assert profile["education"] == ["B.E. Computer, Example College, 2021"]


def test_an_unknown_heading_gets_real_advice_not_a_placeholder():
    text = ("Asha Test\nPune, India | asha@example.com\n\nSkills\nReact\n\nEducation\nB.E., Example College, 2021\n\n"
            "MISCELLANEA\n- Organised a meetup\n")
    actions = " ".join(item["action"] for item in assess_resume(ResumeDocument("r.md", text))["recommendations"])
    assert "A Standard Name" not in actions and "a standard heading" in actions


def test_an_awards_heading_is_recognised():
    text = "Asha Test\nPune, India | asha@example.com\n\nSkills\nReact\n\nHONORS & AWARDS\n- 3rd place nationally\n"
    assert {"heading": "HONORS & AWARDS", "standard": "achievements", "suggested": None} in \
        assess_resume(ResumeDocument("r.md", text))["sections_found"]


# Profile extraction -----------------------------------------------------------------------

LEARNER = ("Asha Test\nPune, India\nSummary\nFrontend engineer building React apps.\nExperience\n"
           "Frontend Engineer | Acme | Jan 2022 - Present\n- Built React and TypeScript apps with Zustand and Vite\n"
           "Skills\nReact, TypeScript, Tailwind CSS, Java (learning), Kubernetes (basic exposure), Machine Learning, "
           "FooLib\nProjects\n- Spam classifier in Python with TensorFlow\n")


def test_skills_marked_learning_are_not_counted():
    profile = build_profile(LEARNER)
    skills = {skill for group in profile["skills"].values() for skill in group}
    assert {"Java", "Kubernetes"} <= set(profile["skills_learning"]) and not {"Java", "Kubernetes"} & skills
    assert "Machine Learning" in skills  # "learning" inside a skill name is not a qualifier


def test_a_skill_also_used_plainly_is_not_downgraded():
    assert "Java" not in qualified_skills("Skills: Java (learning)\n- Built Java services")


def test_target_roles_follow_the_current_title_and_summary_not_projects():
    profile = build_profile(LEARNER)
    families = [role["family"] for role in profile["target_roles"]]
    assert families[0] == "frontend" and "ml_ai" not in families[:4] and "devops_sre" not in families


def test_modern_frontend_tools_are_recognised():
    assert set(find_skills("Zustand, TanStack Query, React Query, Tailwind CSS, Vite, Zod, Vitest, Playwright, Storybook")) \
        >= {"Zustand", "TanStack Query", "Tailwind CSS", "Vite", "Zod", "Testing", "Storybook"}


def test_unrecognised_skills_are_logged():
    assert build_profile(LEARNER)["unrecognized_skills"] == ["FooLib"]


def test_a_draft_profile_is_flagged_until_reviewed():
    profile = build_profile(LEARNER)
    assert profile["reviewed"] is False and profile_warning(profile)
    assert profile_warning({**profile, "reviewed": True}) == ""
    assert profile_warning({"candidate": {}}) == ""  # profiles saved before the flag existed


# Location ---------------------------------------------------------------------------------

@pytest.mark.parametrize("location", ["Pune, India", "Mumbai, Maharashtra, India", "Navi Mumbai"])
def test_a_state_in_the_profile_matches_its_cities(location):
    targets = candidate_targets({"candidate": {"location": "Maharashtra, India"}, "preferred_locations": []}, {})
    assert match_location({"location": location, "remote": False, "description": ""}, targets).status == "match"


def test_another_state_is_not_a_match():
    targets = candidate_targets({"candidate": {"location": "Maharashtra, India"}, "preferred_locations": []}, {})
    assert match_location({"location": "Bengaluru, India", "remote": False, "description": ""}, targets).status == "partial"


def test_a_city_target_does_not_match_the_rest_of_its_state_fully():
    result = match_location({"location": "Mumbai, India", "remote": False, "description": ""}, ["Pune, India"])
    assert result.status == "partial" and "Same state" in result.reason


# Search and resilience --------------------------------------------------------------------

def test_a_comma_separated_location_is_split_into_searches(profile):
    queries = build_search_queries(profile, ["lever"], location_filter="Remote,India")
    terms = [item["search_terms"] for item in queries]
    assert not any("Remote,India" in term for term in terms)
    assert any(term.endswith("Remote") for term in terms) and any(term.endswith("India") for term in terms)
    assert all("site:" not in term for term in terms) and all("site:" in item["query"] for item in queries)


def test_a_blocked_network_stops_after_three_boards_with_one_message(capsys, tmp_path, monkeypatch):
    import search_jobs
    from conftest import FIXTURES, RecordedClient
    client = RecordedClient(failures={"": "network"})
    monkeypatch.setattr(search_jobs, "HttpClient", lambda **_: client)
    boards = [arg for slug in ("a", "b", "c", "d", "e") for arg in ("--board", f"lever:{slug}")]
    code = search_jobs.run(search_jobs.parse_arguments(["--resume", str(FIXTURES / "synthetic_resume.md"),
                                                        "--data-dir", str(tmp_path), "--source", "lever", *boards]))
    error = capsys.readouterr().err
    assert code == 1 and "Could not reach any job board" in error
    assert len(client.requested) == 3


@pytest.mark.parametrize("markup, system", [
    ('<a href="https://acme.darwinbox.in/ms/candidate/careers">Careers</a>', "Darwinbox"),
    ('<iframe src="https://acme.keka.com/careers/"></iframe>', "Keka"),
    ('<a href="https://acme.wd3.myworkdayjobs.com/External">Jobs</a>', "Workday"),
])
def test_unsupported_hiring_systems_are_named(markup, system):
    assert unsupported_hiring_system(markup, "https://acme.example/careers") == system


def test_an_ordinary_page_names_no_hiring_system():
    assert unsupported_hiring_system("<p>We are hiring</p>", "https://acme.example/careers") == ""


# Usability --------------------------------------------------------------------------------

def test_pasted_linkedin_text_supplies_its_own_title_company_and_location(tmp_path):
    path = tmp_path / "job.txt"
    path.write_text("Frontend Engineer\nAcme Payments · Pune, Maharashtra, India · 2 days ago\nAbout the job\n"
                    "Requirements\n- React and TypeScript\n" + FILLER, encoding="utf-8")
    job = match_job.job_from_text(str(path))
    assert (job["title"], job["company"], job["location"]) == ("Frontend Engineer", "Acme Payments",
                                                               "Pune, Maharashtra, India")


def test_labelled_fields_are_read_and_flags_still_win(tmp_path):
    path = tmp_path / "job.txt"
    path.write_text("Job Title: UI Developer\nCompany: Globex\nLocation: Remote\n" + FILLER, encoding="utf-8")
    job = match_job.job_from_text(str(path), company="Initech")
    assert (job["title"], job["company"], job["location"]) == ("UI Developer", "Initech", "Remote")


def test_the_verdict_comes_first_and_the_scores_stay_apart(profile):
    job = build_job(description="Requirements\n- 3+ years of Java and Spring Boot\n- PostgreSQL and Docker\n" + FILLER)
    scored = score_job(job, profile, {}, "Pune")
    ats = {"ats_score": 60, "recommendations": [{}, {}]}
    text = format_separate_scores(ats, scored)
    assert text.startswith("VERDICT: Apply, after fixing the resume") and "2 fix(es)" in text
    assert "ATS Readiness" in text and "Job Match" in text


def test_matched_jobs_count_towards_skill_gaps(capsys, tmp_path, profile):
    store = JobStore(tmp_path)
    job = score_job(build_job(description="Requirements\n- Java, Spring Boot, PostgreSQL and Rust\n" + FILLER), profile)
    store.record_match(job)
    assert skill_gaps.run(skill_gaps.parse_arguments(["--data-dir", str(tmp_path), "--min-score", "0"])) == 0
    assert "| Rust | 1 | 0 |" in capsys.readouterr().out
    assert json.loads((tmp_path / "matched_jobs.json").read_text(encoding="utf-8"))[0]["date_matched"]


# Second pass: closed listings, the blocked-network fallback, draft structure -------------

@pytest.mark.parametrize("text, url", [
    ("Frontend Engineer\nThis job is no longer accepting applications.\n", ""),
    ("Sorry, this position has been filled.\n", ""),
    ("Frontend Engineer\nRequirements\n- React\n", "https://job-boards.greenhouse.io/acme/jobs/1?error=true"),
])
def test_closed_listings_are_recognised(text, url):
    assert closed_listing_reason(text, url)


def test_an_open_listing_mentioning_closed_work_is_not_closed():
    assert closed_listing_reason("Frontend Engineer\nRequirements\n- React\n" + FILLER.replace(". ", ".\n")
                                 + "\nThe role we filled last year is no longer available.") == ""


def test_a_closed_pasted_listing_is_refused_not_scored(tmp_path):
    path = tmp_path / "job.txt"
    path.write_text("Frontend Engineer\nThis job is no longer accepting applications.\n" + FILLER, encoding="utf-8")
    with pytest.raises(ValueError, match="closed"):
        match_job.job_from_text(str(path))


def test_a_folder_of_fetched_listings_is_scored_together(capsys, tmp_path, profile, monkeypatch):
    monkeypatch.setattr(match_job, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(match_job, "SYNTHETIC_DATA_DIR", tmp_path / "data")
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    fetched = tmp_path / "fetched"
    fetched.mkdir()
    (fetched / "a.txt").write_text("Backend Engineer\nRequirements\n- 3+ years of Java and Spring Boot\n" + FILLER,
                                   encoding="utf-8")
    (fetched / "b.md").write_text("Data Engineer\nRequirements\n- Scala and Spark\n" + FILLER, encoding="utf-8")
    (fetched / "c.txt").write_text("Old Role\nThis job has expired.\n", encoding="utf-8")
    (fetched / "notes.json").write_text("{}", encoding="utf-8")
    code = match_job.run(match_job.parse_arguments(["--text-dir", str(fetched), "--profile",
                                                    str(tmp_path / "profile.json"), "--source-name", "Greenhouse"]))
    out = capsys.readouterr().out
    assert code == 0 and "| File |" in out and "2 scored, 1 skipped" in out and "c.txt: this listing has closed" in out
    assert out.index("a.txt") < out.index("b.md")  # best first
    assert len(json.loads((tmp_path / "data" / "matched_jobs.json").read_text(encoding="utf-8"))) == 2


def test_an_empty_folder_is_an_error(tmp_path, profile):
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    assert match_job.run(match_job.parse_arguments(["--text-dir", str(tmp_path / "none"), "--profile",
                                                    str(tmp_path / "profile.json")])) == 2


def test_a_network_failure_is_not_blamed_on_the_board_name(capsys, tmp_path):
    import companies
    from conftest import RecordedClient
    code = companies.run(companies.parse_arguments(["--data-dir", str(tmp_path), "add", "lever:acme"]),
                         RecordedClient(failures={"": "network"}))
    out = capsys.readouterr().out
    assert code == 1 and "could not be reached" in out and "--no-check" in out and "Check the company's" not in out


def test_a_missing_board_still_says_check_the_name(capsys, tmp_path):
    import companies
    from conftest import RecordedClient
    companies.run(companies.parse_arguments(["--data-dir", str(tmp_path), "add", "lever:acme"]),
                  RecordedClient(failures={"": "not_found"}))
    assert "Check the company's board name" in capsys.readouterr().out


def test_a_location_line_under_a_job_stays_in_its_heading():
    _, blocks = group_experience(["SDE 1 | Solvative | Sep 2023 - Present", "Remote | IT Services",
                                  "- Built a React dashboard", "- Wrote tests"])
    assert blocks[0].body == ["Built a React dashboard", "Wrote tests"]
    assert "Remote | IT Services" in blocks[0].heading_lines


PROJECTS = ["ShopKart | Next.js, Stripe", "- Built checkout with Next.js and Stripe for", "guest and signed-in users",
            "- Added order tracking", "ChatDesk | Python, Flask", "- Wrote a Flask API for support tickets"]


def test_projects_keep_their_bullets_and_wrapped_lines():
    assert group_projects(PROJECTS) == [
        ["ShopKart | Next.js, Stripe", "Built checkout with Next.js and Stripe for guest and signed-in users",
         "Added order tracking"],
        ["ChatDesk | Python, Flask", "Wrote a Flask API for support tickets"]]


def test_the_draft_moves_whole_projects_not_their_bullets():
    text = ("Asha Test\nPune, India | asha@example.com\n\nProjects\n" + "\n".join(PROJECTS)
            + "\n\nEducation\nB.E., Example College, 2021\n")
    job = build_job(title="Python Developer", description="Requirements\n- Python and Flask\n" + FILLER)
    draft = build_draft(ResumeDocument("r.md", text), job)
    projects = draft.split("## Projects")[1].split("##")[0]
    assert projects.index("ChatDesk") < projects.index("ShopKart")
    assert projects.index("ShopKart") < projects.index("Added order tracking")
    assert "- guest and signed-in users" not in projects


RESUME = ("Asha Test\nPune, India | asha@example.com\n\nExperience\n"
          "SDE 1 | Solvative | Sep 2023 - Present\nRemote | IT Services\n"
          "- Containerised the React frontend with Docker and cut build times\n"
          "- Built reusable form components with Zod validation\n"
          "Intern | Globex | Jan 2023 - Aug 2023\n- Fixed accessibility issues across the checkout pages\n"
          "\nEducation\nB.E., Example College, 2022\n")


def test_a_rewrite_that_keeps_structure_passes():
    rewritten = RESUME.replace("cut build times", "reduced build times")
    assert structure_problems(ResumeDocument("a.md", RESUME), ResumeDocument("b.md", rewritten)) == []


def test_a_draft_is_structurally_sound():
    draft = build_draft(ResumeDocument("a.md", RESUME), None)
    assert structure_problems(ResumeDocument("a.md", RESUME), ResumeDocument("b.md", draft)) == []


@pytest.mark.parametrize("broken, kind", [
    (RESUME.replace("Remote | IT Services\n", "- Remote | IT Services\n"), "not a bullet"),
    (RESUME.replace("with Docker and cut build times", "with Docker\n- and cut build times"), "split bullet"),
    (RESUME.replace("- Fixed accessibility issues across the checkout pages\n", "").replace(
        "- Built reusable", "- Fixed accessibility issues across the checkout pages\n- Built reusable"), "moved bullet"),
])
def test_a_broken_structure_is_rejected(broken, kind):
    problems = structure_problems(ResumeDocument("a.md", RESUME), ResumeDocument("b.md", broken))
    assert kind in [problem["kind"] for problem in problems]


def test_verify_fails_on_structure_alone():
    broken = RESUME.replace("Remote | IT Services\n", "- Remote | IT Services\n")
    result = verify(ResumeDocument("a.md", RESUME), ResumeDocument("b.md", broken), None, set())
    assert not result["passed"] and not result["unsupported_claims"] and result["structure_problems"]
    assert "breaks the resume's structure" in format_verification(result)
