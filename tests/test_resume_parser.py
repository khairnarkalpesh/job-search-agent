import json

import jsonschema
import pytest

from conftest import FIXTURES, REFERENCE_DATE, SKILL_ROOT
from resume_parser import (ResumeParseError, build_profile, load_profile_from_resume, read_resume_text,
                           remove_contact_details)


@pytest.mark.parametrize("extension", ["md", "txt", "docx", "pdf"])
def test_every_resume_format_gives_the_same_core_profile(extension):
    profile = load_profile_from_resume(FIXTURES / f"synthetic_resume.{extension}")
    assert profile["synthetic"] is True
    assert profile["candidate"]["name"] == "Asha Testcandidate"
    assert profile["candidate"]["location"] == "Pune, India"
    assert profile["candidate"]["current_role"] == "Software Engineer II"
    assert "Java" in profile["skills"]["programming_languages"]
    assert "Spring Boot" in profile["skills"]["frameworks"]
    assert [job["company"] for job in profile["experience"]] == ["Northwind Payments", "Contoso Logistics"]


def test_profile_matches_schema(profile):
    schema = json.loads((SKILL_ROOT / "schemas" / "candidate-profile.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(profile, schema)


def test_contact_details_never_reach_the_profile(profile):
    stored = json.dumps(profile).lower()
    for private_value in ("example.com", "98765", "43210", "linkedin"):
        assert private_value not in stored


@pytest.mark.parametrize("line", ["+91 98765 43210", "(415) 555-2671", "98765-43210"])
def test_phone_numbers_are_removed(line):
    assert not any(character.isdigit() for character in remove_contact_details(line))


@pytest.mark.parametrize("line", ["Engineer | Acme | 2020 - 2024", "2019 to 2021", "Jan 2020 - Mar 2022", "01/2020 - 03/2022"])
def test_date_ranges_are_not_mistaken_for_phone_numbers(line):
    assert remove_contact_details(line) == line


def test_street_address_is_reduced_to_city_and_country():
    text = "Test Person\n14 Hill Road, Kothrud, Pune, India\n\nSkills\nJava\n\nExperience\nEngineer | Acme | 2020 - 2021\n- Java work"
    assert build_profile(text, REFERENCE_DATE)["candidate"]["location"] == "Pune, India"


def test_years_are_calculated_from_dates_and_marked_inferred(profile):
    assert profile["candidate"]["years_of_experience"] == pytest.approx(5.2, abs=0.2)
    entry = next(item for item in profile["evidence"] if "years of experience" in item["item"])
    assert entry["type"] == "inferred"


def test_overlapping_jobs_are_not_counted_twice():
    text = ("Experience\nEngineer | First | Jan 2020 - Jan 2022\n- Java\n"
            "Engineer | Second | Jan 2021 - Jan 2022\n- Java\n")
    assert build_profile(text, REFERENCE_DATE)["candidate"]["years_of_experience"] == 2.0


def test_a_stated_total_is_explicit():
    text = "Summary\n7 years of experience building Java services\n\nExperience\nEngineer | Acme | 2024 - 2025\n- Java"
    profile = build_profile(text, REFERENCE_DATE)
    assert profile["candidate"]["years_of_experience"] == 7
    assert any(item["type"] == "explicit" and "7 years" in item["item"] for item in profile["evidence"])


def test_skills_section_is_explicit_evidence(profile):
    java = next(item for item in profile["evidence"] if item["item"] == "Java")
    assert java["type"] == "explicit"
    assert java["evidence"] == "Explicitly listed in Skills section"


def test_skills_not_in_the_resume_are_not_invented(profile):
    all_skills = {skill for skills in profile["skills"].values() for skill in skills}
    assert not all_skills & {"Kubernetes", "Python", "Go", "Node.js", "Terraform"}


def test_nothing_is_assumed_about_preferences(profile):
    assert profile["preferred_locations"] == []
    assert profile["remote_preference"] is None
    assert profile["certifications"] == []


def test_target_roles_fit_the_resume_with_reasons(profile):
    titles = [role["title"] for role in profile["target_roles"]]
    assert titles[:3] == ["Backend Engineer", "Backend Developer", "Software Engineer"]
    assert "Java Developer" in titles
    assert not {"Machine Learning Engineer", "iOS Developer", "Data Engineer"} & set(titles)
    for role in profile["target_roles"]:
        assert 0 <= role["role_relevance"] <= 1
        assert role["confidence"] in ("high", "medium", "low")
        assert role["reason"]


def test_listed_skill_without_work_history_gets_no_language_title():
    text = "Skills\nJava, Python\n\nExperience\nSoftware Engineer | Acme | 2020 - 2024\n- Built Java services with Spring Boot, SQL and REST APIs"
    titles = [role["title"] for role in build_profile(text, REFERENCE_DATE)["target_roles"]]
    assert "Java Developer" in titles
    assert "Python Developer" not in titles


@pytest.mark.parametrize("name,content,expected", [
    ("resume.exe", b"binary", "Unsupported"),
    ("empty.txt", b"  ", "almost no extractable text"),
    ("broken.pdf", b"not really a pdf", "Could not read"),
    ("broken.docx", b"not really a docx", "Could not read"),
])
def test_unreadable_resumes_give_a_clear_error(tmp_path, name, content, expected):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(ResumeParseError, match=expected):
        read_resume_text(path)


def test_missing_file_gives_a_clear_error(tmp_path):
    with pytest.raises(ResumeParseError, match="not found"):
        read_resume_text(tmp_path / "nothing.pdf")
