import copy
import json

import jsonschema
import pytest

from conftest import SKILL_ROOT, build_job
from job_storage import JobStore
from score_jobs import (COMPONENT_MAXIMUMS, SCORE_CAP_ONE_MAJOR_GAP, SCORE_CAP_SEVERAL_MAJOR_GAPS, category_for, score_job)


def requirement_types(job, bucket):
    return {item["type"] for item in job["hard_requirements"][bucket]}


def test_weights_add_up_to_100():
    assert sum(COMPONENT_MAXIMUMS.values()) == 100
    assert COMPONENT_MAXIMUMS == {"skills": 30, "experience": 20, "role": 15, "qualifications": 15,
                                  "technology": 10, "location": 5, "seniority": 5}


def test_total_is_the_sum_of_its_components(profile):
    job = score_job(build_job(), profile)
    breakdown = job["score_breakdown"]
    assert breakdown["uncapped_total"] == round(sum(breakdown[name]["score"] for name in COMPONENT_MAXIMUMS))
    assert job["match_score"] == breakdown["uncapped_total"]


def test_strong_listing_scores_high_and_explains_itself(profile):
    job = score_job(build_job(), profile)
    assert job["match_score"] >= 85
    assert any("Java" in reason for reason in job["why_match"])
    assert all(job["score_breakdown"][name]["detail"] for name in COMPONENT_MAXIMUMS)


def test_kubernetes_preference_is_shown_as_partial_not_exact(profile):
    job = score_job(build_job(), profile)
    kubernetes = next(item for item in job["matched_skills"] if item["skill"] == "Kubernetes")
    assert (kubernetes["match"], kubernetes["importance"]) == ("TRANSFERABLE", "preferred")


def test_unrelated_stack_scores_lower_and_lists_gaps(profile):
    description = ("Requirements\n- 3+ years with Ruby on Rails\n- Must have Elasticsearch\n- GraphQL\n- Terraform\n"
                   + "We build tools. " * 25)
    job = score_job(build_job(title="Ruby Developer", description=description), profile)
    assert job["match_score"] < score_job(build_job(), profile)["match_score"] - 25
    assert {"Ruby on Rails", "Elasticsearch", "Terraform"} <= set(job["missing_skills"])
    assert job["gaps"]


def test_a_major_gap_cannot_hide_behind_a_high_score(profile):
    description = ("Requirements\n- 12+ years of experience with Java and Spring Boot\n- REST APIs and PostgreSQL\n- Docker and AWS\n"
                   + "We build payment systems. " * 15)
    job = score_job(build_job(description=description), profile)
    assert job["score_breakdown"]["uncapped_total"] > SCORE_CAP_ONE_MAJOR_GAP
    assert job["match_score"] == SCORE_CAP_ONE_MAJOR_GAP
    assert "cap_applied" in job["score_breakdown"]
    assert job["hard_requirements"]["hard_requirements_failed"][0]["severity"] == "major"
    assert any(gap.startswith("Major Gap") and "12+" in gap for gap in job["gaps"])


def test_several_major_gaps_cap_lower(profile):
    description = ("Requirements\n- 12+ years of experience with Java and Spring Boot\n- Must have Elasticsearch\n- REST APIs\n- Docker\n"
                   + "We build payment systems. " * 15)
    job = score_job(build_job(location="Berlin, Germany", description=description), profile)
    assert job["match_score"] <= SCORE_CAP_SEVERAL_MAJOR_GAPS


def test_small_experience_shortfall_is_flagged_but_not_capped(profile):
    description = "Requirements\n- 6+ years of experience with Java and Spring Boot\n- REST APIs\n- Docker\n" + "We ship. " * 40
    job = score_job(build_job(description=description), profile)
    failed = job["hard_requirements"]["hard_requirements_failed"]
    assert [item["severity"] for item in failed] == ["minor"]
    assert "cap_applied" not in job["score_breakdown"]


def test_every_requirement_lands_in_one_list(profile):
    job = score_job(build_job(), profile)
    assert set(job["hard_requirements"]) == {"hard_requirements_met", "hard_requirements_failed", "unknown_requirements"}
    assert {"experience", "location"} <= requirement_types(job, "hard_requirements_met")


def test_experience_in_preferred_section_is_not_a_requirement(profile):
    description = ("Requirements\n- Java and Spring Boot\n- REST APIs\nNice to have\n- 15+ years of experience in banking\n"
                   + "We ship. " * 40)
    job = score_job(build_job(description=description), profile)
    assert "experience" not in requirement_types(job, "hard_requirements_failed")


def test_company_age_is_not_read_as_experience(profile):
    description = "Requirements\n- Java and Spring Boot\n- REST APIs\n- For over 30 years our company has been building products\n" + "x " * 200
    job = score_job(build_job(description=description), profile)
    assert "experience" not in requirement_types(job, "hard_requirements_failed")


@pytest.mark.parametrize("line,bucket", [
    ("Master's degree in Computer Science required", "hard_requirements_failed"),
    ("Bachelor's degree in Computer Science required", "hard_requirements_met"),
    ("Master's degree or equivalent experience", "unknown_requirements"),
])
def test_degree_requirement(profile, line, bucket):
    job = score_job(build_job(description=f"Requirements\n- {line}\n- Java, REST APIs\n- Docker\n" + "x " * 200), profile)
    assert "degree" in requirement_types(job, bucket)


def test_mandatory_certification_is_a_major_gap(profile):
    job = score_job(build_job(description="Requirements\n- CISSP certification is required\n- Java, REST APIs, Docker\n" + "x " * 200), profile)
    assert any(item["type"] == "certification" and item["severity"] == "major"
               for item in job["hard_requirements"]["hard_requirements_failed"])


def test_one_of_several_options_is_enough(profile):
    job = score_job(build_job(description="Requirements\n- Must have strong experience in Java or Go\n- REST APIs\n- Docker\n" + "x " * 200), profile)
    assert "technology" not in requirement_types(job, "hard_requirements_failed")


def test_all_options_missing_fails_once(profile):
    job = score_job(build_job(description="Requirements\n- Must know Ruby or Go\n- Java and Docker\n" + "x " * 200), profile)
    failures = [item for item in job["hard_requirements"]["hard_requirements_failed"] if item["type"] == "technology"]
    assert len(failures) == 1 and "Needs one of" in failures[0]["detail"]


def test_fundamentals_missing_from_a_resume_are_not_hard_failures(profile):
    job = score_job(build_job(description="Requirements\n- Strong system design and OOP fundamentals\n- Java, REST APIs, Docker\n" + "x " * 200), profile)
    assert "technology" not in requirement_types(job, "hard_requirements_failed")


def test_work_authorization_is_unknown_without_saved_rights(profile):
    description = "Requirements\n- Java, Docker, REST APIs\nYou must be authorized to work in the United States.\n" + "x " * 200
    job = score_job(build_job(location="Remote", description=description), profile)
    assert "work_authorization" in requirement_types(job, "unknown_requirements")


def test_work_authorization_uses_saved_rights(profile):
    description = "Requirements\n- Java, Docker, REST APIs\nYou must be authorized to work in the United States.\n" + "x " * 200
    job = score_job(build_job(location="Remote", description=description), profile, {"work_authorization": ["India"]})
    assert "work_authorization" in requirement_types(job, "hard_requirements_failed")


def test_clearance_is_never_guessed(profile):
    description = "Requirements\n- Java, Docker, REST APIs\nMust hold an active security clearance.\n" + "x " * 200
    assert "work_authorization" in requirement_types(score_job(build_job(description=description), profile), "unknown_requirements")


def test_required_language_is_checked_against_resume(profile):
    german = "Requirements\n- Fluent German is required\n- Java, Docker, REST APIs\n" + "x " * 200
    hindi = "Requirements\n- Fluent Hindi is required\n- Java, Docker, REST APIs\n" + "x " * 200
    assert "language" in requirement_types(score_job(build_job(description=german), profile), "hard_requirements_failed")
    assert "language" in requirement_types(score_job(build_job(description=hindi), profile), "hard_requirements_met")


def test_listing_with_missing_requirements_is_not_reliable(profile):
    job = score_job(build_job(description="We are hiring."), profile)
    assert job["reliable"] is False
    assert job["score_breakdown"]["skills"]["detail"] == "No skills found in listing"


def test_one_lucky_skill_is_not_reliable(profile):
    job = score_job(build_job(title="Senior Engineer, Footwear", description="Testing shoes. " * 40), profile)
    assert job["reliable"] is False


def test_title_of_another_family_does_not_match_a_target(profile):
    job = score_job(build_job(title="Software Development Engineer in Test"), profile)
    assert job["score_breakdown"]["role"]["score"] < 8


def test_scoring_does_not_change_the_profile(profile):
    before = copy.deepcopy(profile)
    score_job(build_job(), profile)
    assert profile == before


@pytest.mark.parametrize("score,label", [(100, "Excellent Match"), (90, "Excellent Match"), (89, "Strong Match"), (80, "Strong Match"),
                                         (79, "Good Match"), (70, "Good Match"), (69, "Possible Match"), (60, "Possible Match"),
                                         (59, "Low Match"), (0, "Low Match")])
def test_match_categories(score, label):
    assert category_for(score) == label


def test_stored_job_matches_schema(profile, tmp_path):
    job = score_job(build_job(), profile)
    JobStore(tmp_path).record_results([job], {})
    schema = json.loads((SKILL_ROOT / "schemas" / "job.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(job, schema)
