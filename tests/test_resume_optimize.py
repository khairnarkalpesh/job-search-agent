"""resume_facts.py and resume_optimize.py: rewrites keep to the facts, and are checked.

Every "rewrite" here is a synthetic edit of a synthetic resume, made to test one rule.
"""
import json

import jsonschema
import pytest

import resume_optimize
from ats_readiness import assess_resume
from conftest import SKILL_ROOT, build_job
from resume_facts import ResumeFacts, dropped_facts, unsupported_claims
from resume_layout import ResumeDocument, inspect_resume

ORIGINAL = """SYNTHETIC TEST RESUME - NOT A REAL PERSON - FOR TESTING ONLY
Asha Testcandidate
Pune, India | asha.testcandidate@example.com | +91 98765 43210

Summary
Hard-working team player and backend engineer building Java and Spring Boot services for payments.

Skills
Java, Spring Boot, Hibernate, REST APIs, PostgreSQL, Redis, Kafka, Docker, AWS, Git, React

Experience
Software Engineer II | Northwind Payments | Jan 2023 - Present
- Responsible for the React admin screen
- Built Spring Boot microservices in Java handling card settlement over REST APIs
- Reduced PostgreSQL query latency by 40% using Redis caching

Software Engineer | Contoso Logistics | Jul 2021 - Dec 2022
- Developed Java and Hibernate services backed by PostgreSQL
- Published shipment events through Kafka

Projects
- A React dashboard for a local library
- A Kafka consumer in Java that archives settlement files to AWS

Education
Bachelor of Engineering in Computer Engineering, Example Institute of Technology, 2021

Certifications
AWS Certified Developer - Associate, 2022
"""

FILLER = "We build payment systems for banks. " * 12
JOB = build_job(description="Requirements\n- 3+ years of Java and Spring Boot\n- RESTful APIs and PostgreSQL\n"
                            "- Kubernetes\nNice to have\n- Kafka\n" + FILLER)
CHECK_SCHEMA = json.loads((SKILL_ROOT / "schemas" / "optimization-check.schema.json").read_text(encoding="utf-8"))


def doc(text):
    return ResumeDocument("resume.md", text)


def claims(rewritten, evidence=frozenset()):
    return unsupported_claims(ResumeFacts.of(ORIGINAL), ResumeFacts.of(rewritten), set(evidence))


def kinds(found):
    return {(item["kind"], item["value"]) for item in found}


# The draft ----------------------------------------------------------------------------

@pytest.fixture
def draft():
    return resume_optimize.build_draft(doc(ORIGINAL), JOB)


def test_the_draft_passes_its_own_fact_check(draft):
    result = resume_optimize.verify(doc(ORIGINAL), doc(draft), JOB, set())
    assert result["passed"], result["unsupported_claims"] + result["dropped_facts"]


def test_the_draft_keeps_every_employer_title_date_education_and_certification(draft):
    for fact in ("Northwind Payments", "Contoso Logistics", "Software Engineer II", "Jan 2023 - Present",
                 "Jul 2021 - Dec 2022", "Bachelor of Engineering in Computer Engineering, Example Institute of Technology, 2021",
                 "AWS Certified Developer - Associate, 2022", "40%"):
        assert fact in draft


def test_the_draft_puts_the_jobs_skills_first_and_adds_its_wording(draft):
    skills = draft.split("## Skills")[1].split("##")[0]
    assert "Languages: Java" in skills and "Frameworks: Spring Boot" in skills
    assert "REST APIs (RESTful APIs)" in skills


def test_the_draft_never_adds_a_skill_the_resume_lacks(draft):
    assert "Kubernetes" not in draft


def test_the_draft_moves_relevant_bullets_up_and_keeps_their_words(draft):
    northwind = draft.split("Northwind Payments")[1].split("Contoso")[0]
    assert northwind.index("Built Spring Boot") < northwind.index("Responsible for the React admin screen")


def test_the_draft_removes_filler_and_uses_standard_headings(draft):
    assert "Hard-working" not in draft and "team player" not in draft
    assert draft.split("## Summary\n")[1].startswith("Backend engineer building Java")
    assert [line for line in draft.splitlines() if line.startswith("## ")] == [
        "## Summary", "## Skills", "## Experience", "## Projects", "## Education", "## Certifications"]


def test_a_home_made_heading_becomes_a_standard_one():
    text = ORIGINAL.replace("Experience\nSoftware Engineer II", "WHERE I HAVE WORKED\nSoftware Engineer II")
    draft = resume_optimize.build_draft(doc(text), JOB)
    assert "## Experience" in draft and "WHERE I HAVE WORKED" not in draft
    assert resume_optimize.verify(doc(text), doc(draft), JOB, set())["passed"]


def test_the_draft_scores_at_least_as_well_as_the_original(draft):
    assert assess_resume(doc(draft), JOB)["ats_score"] >= assess_resume(doc(ORIGINAL), JOB)["ats_score"]


# The fact check -----------------------------------------------------------------------

def test_an_added_skill_is_rejected():
    rewritten = ORIGINAL.replace("Docker, AWS", "Docker, Kubernetes, AWS")
    assert ("skill", "Kubernetes") in kinds(claims(rewritten))


def test_a_skill_the_reviewed_profile_shows_is_allowed():
    rewritten = ORIGINAL.replace("Docker, AWS", "Docker, Kubernetes, AWS")
    assert claims(rewritten, {"Kubernetes"}) == []


def test_an_invented_metric_is_rejected():
    rewritten = ORIGINAL.replace("over REST APIs", "over REST APIs, increasing throughput by 47%")
    assert ("figure", "47") in kinds(claims(rewritten))


def test_a_changed_figure_is_rejected():
    assert ("figure", "60") in kinds(claims(ORIGINAL.replace("40%", "60%")))


def test_an_invented_employer_title_or_date_is_rejected():
    # Inserted at the end of the Experience section, so it is read as one more job.
    rewritten = ORIGINAL.replace("Projects\n", "Senior Engineer | Fabrikam Bank | Jan 2019 - Jun 2021\n- Built Java services\n\nProjects\n")
    found = kinds(claims(rewritten))
    assert ("employer", "Fabrikam Bank") in found and ("title", "Senior Engineer") in found
    assert ("dates", "jan 2019 - jun 2021") in found


def test_a_promoted_title_is_rejected():
    rewritten = ORIGINAL.replace("Software Engineer | Contoso", "Lead Engineer | Contoso")
    assert ("title", "Lead Engineer") in kinds(claims(rewritten))


def test_a_stretched_date_is_rejected():
    rewritten = ORIGINAL.replace("Jul 2021 - Dec 2022", "Jan 2020 - Dec 2022")
    assert ("dates", "jan 2020 - dec 2022") in kinds(claims(rewritten))


def test_an_upgraded_degree_is_rejected():
    rewritten = ORIGINAL.replace("Bachelor of Engineering", "Master of Engineering")
    assert any(item["kind"] == "education" and "master" in item["reason"] for item in claims(rewritten))


def test_an_added_certification_is_rejected():
    rewritten = ORIGINAL.replace("AWS Certified Developer - Associate, 2022",
                                 "AWS Certified Developer - Associate, 2022\nCKA, 2024")
    found = claims(rewritten)
    assert ("certification", "cka") in kinds(found) and ("figure", "2024") in kinds(found)


def test_dropped_facts_are_reported():
    shortened = ORIGINAL.split("Software Engineer | Contoso")[0] + "\nEducation\nExample Institute of Technology\n"
    lost = kinds(dropped_facts(ResumeFacts.of(ORIGINAL), ResumeFacts.of(shortened)))
    assert ("employer", "Contoso Logistics") in lost and ("dates", "jul 2021 - dec 2022") in lost
    assert any(kind == "certification" for kind, _ in lost)
    assert any(kind == "education" for kind, _ in lost)


def test_rewording_a_bullet_without_new_facts_passes():
    rewritten = ORIGINAL.replace("- Responsible for the React admin screen", "- Built the React admin screen")
    rewritten = rewritten.replace("over REST APIs", "over RESTful APIs")
    assert claims(rewritten) == []
    assert dropped_facts(ResumeFacts.of(ORIGINAL), ResumeFacts.of(rewritten)) == []


def test_an_invented_rewrite_is_rejected_even_when_it_scores_higher():
    padded = ORIGINAL.replace("Docker, AWS", "Docker, Kubernetes, AWS").replace(
        "- Reduced PostgreSQL", "- Ran services on Kubernetes for 3 million users\n- Reduced PostgreSQL")
    result = resume_optimize.verify(doc(ORIGINAL), doc(padded), JOB, set())
    assert result["comparison"]["ats_score"]["after"] > result["comparison"]["ats_score"]["before"]
    assert not result["passed"]
    text = resume_optimize.format_verification(result)
    assert "REJECTED" in text and "does not count" in text


# The plan -----------------------------------------------------------------------------

def test_the_plan_separates_what_to_emphasise_from_what_not_to_add():
    plan = resume_optimize.build_plan(doc(ORIGINAL), JOB, None)
    assert {"Java", "Spring Boot", "PostgreSQL"} <= set(plan["emphasise"])
    assert plan["do_not_add"] == ["Kubernetes"]
    assert {"job_term": "RESTful APIs", "resume_term": "REST APIs"} in plan["use_job_wording"]
    assert plan["job_match"] is None  # no profile, so no Job Match number


def test_the_plan_asks_for_missing_information_instead_of_inventing_it():
    plain = ORIGINAL.replace(" by 40%", "")
    plan = resume_optimize.build_plan(doc(plain), JOB, None)
    questions = " ".join(plan["additional_information_required"])
    assert "Kubernetes" in questions and "figures" in questions


def test_the_plan_lists_weak_bullets_and_filler():
    plan = resume_optimize.build_plan(doc(ORIGINAL), JOB, None)
    assert {"bullet": "Responsible for the React admin screen", "reason": "describes a duty; start with what you did"} \
        in plan["bullets_to_strengthen"]
    assert {"hard-working", "team player"} <= set(plan["filler_to_remove"])


def test_the_plan_keeps_the_facts_without_contact_details():
    plan = resume_optimize.build_plan(doc(ORIGINAL), JOB, None)
    assert plan["facts"]["employers"] == ["Northwind Payments", "Contoso Logistics"]
    dumped = json.dumps(plan)
    assert "asha.testcandidate@example.com" not in dumped and "98765" not in dumped


def test_remove_filler_keeps_the_sentence_readable():
    assert resume_optimize.remove_filler("Hard-working, results-driven engineer who ships") == "Engineer who ships"


# Commands -----------------------------------------------------------------------------

def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def run(capsys, *argv):
    code = resume_optimize.run(resume_optimize.parse_arguments(list(argv)))
    return code, capsys.readouterr()


def test_cli_plan_draft_verify_and_export(capsys, tmp_path):
    original = write(tmp_path, "resume.md", ORIGINAL)
    job = write(tmp_path, "job.txt", "Backend Engineer\n" + JOB["description"])
    data = str(tmp_path / "data")
    code, output = run(capsys, "plan", "--resume", original, "--text-file", job, "--data-dir", data)
    assert code == 0 and "Additional information required" in output.out and "Kubernetes" in output.out

    draft = str(tmp_path / "optimized.md")
    code, _ = run(capsys, "draft", "--resume", original, "--text-file", job, "--output", draft)
    assert code == 0

    code, output = run(capsys, "verify", "--resume", original, "--optimized", draft, "--text-file", job, "--data-dir", data)
    assert code == 0 and "VERIFIED" in output.out and "BEFORE AND AFTER" in output.out
    jsonschema.validate(json.loads((tmp_path / "data" / "optimization_check.json").read_text(encoding="utf-8")), CHECK_SCHEMA)

    docx = tmp_path / "optimized.docx"
    code, _ = run(capsys, "export", "--optimized", draft, "--output", str(docx))
    exported = inspect_resume(docx)
    assert code == 0 and exported.layout.tables == 0 and "Northwind Payments" in exported.text
    assert assess_resume(exported)["category_scores"]["formatting"]["score"] == 10


def test_cli_verify_rejects_an_invented_rewrite_with_its_own_exit_code(capsys, tmp_path):
    original = write(tmp_path, "resume.md", ORIGINAL)
    invented = write(tmp_path, "invented.md", ORIGINAL.replace("40%", "75%"))
    code, output = run(capsys, "verify", "--resume", original, "--optimized", invented, "--data-dir", str(tmp_path))
    assert code == resume_optimize.REJECTED_EXIT_CODE and "figure: 75" in output.out


def test_cli_reports_unreadable_input(capsys, tmp_path):
    code, output = run(capsys, "plan", "--resume", str(tmp_path / "missing.docx"))
    assert code == 2 and "Resume not found" in output.err
    code, output = run(capsys, "export", "--optimized", str(tmp_path / "missing.md"), "--output", str(tmp_path / "x.docx"))
    assert code == 2
