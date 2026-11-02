"""match_job.py, companies.py and skill_gaps.py, with the network replaced by recorded responses."""
import json

import pytest

import companies
import match_job
import skill_gaps
from conftest import FIXTURES, RecordedClient, recorded
from job_storage import JobStore, write_json
from resume_parser import load_profile_from_resume
from sources import JobBoard


@pytest.fixture
def profile_file(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(load_profile_from_resume(str(FIXTURES / "synthetic_resume.md"))), encoding="utf-8")
    return str(path)


def match(capsys, *argv, client=None):
    code = match_job.run(match_job.parse_arguments(list(argv)), client or RecordedClient())
    return code, capsys.readouterr()


def test_match_a_job_by_its_board_url(profile_file, capsys):
    item = recorded("lever_onehouse")[0]
    code, output = match(capsys, "--url", item["hostedUrl"], "--profile", profile_file)
    assert code == 0
    assert item["text"] in output.out and "/100" in output.out and "Listing on Lever" in output.out


def test_match_a_smartrecruiters_url_with_the_title_after_the_id(profile_file, capsys):
    posting = recorded("smartrecruiters_boschgroup")["content"][0]
    url = f"https://jobs.smartrecruiters.com/BoschGroup/{posting['id']}-some-title"
    code, output = match(capsys, "--url", url, "--profile", profile_file, "--json")
    assert code == 0 and len(json.loads(output.out)["description"]) > 300


def test_match_pasted_text_from_a_site_without_an_api(profile_file, capsys, tmp_path):
    text = tmp_path / "job.txt"
    text.write_text("Senior Java Developer\nRequirements\n- 4+ years of Java and Spring Boot\n- PostgreSQL, Docker, AWS\n"
                    + "We build payment systems for banks. " * 12, encoding="utf-8")
    code, output = match(capsys, "--text-file", str(text), "--source-name", "LinkedIn", "--location", "Pune, India",
                         "--profile", profile_file)
    assert code == 0
    assert "Senior Java Developer" in output.out and "Source: LinkedIn (pasted text)" in output.out


def test_match_unknown_job_url_is_reported(profile_file, capsys):
    code, output = match(capsys, "--url", "https://jobs.lever.co/Onehouse/not-a-real-id", "--profile", profile_file)
    assert code == 1 and "no open job" in output.err


def test_match_without_a_profile_says_what_to_do(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(match_job, "DATA_DIR", tmp_path)
    code, output = match(capsys, "--url", "https://jobs.lever.co/x/1")
    assert code == 2 and "/job-profile" in output.err


def test_match_with_a_resume_given_as_the_profile_is_explained(capsys):
    code, output = match(capsys, "--url", "https://jobs.lever.co/x/1", "--profile", str(FIXTURES / "synthetic_resume.md"))
    assert code == 2 and "not a resume" in output.err


def run_companies(capsys, tmp_path, *argv, client=None):
    code = companies.run(companies.parse_arguments(["--data-dir", str(tmp_path), *argv]), client or RecordedClient())
    return code, capsys.readouterr().out


def test_companies_add_list_and_remove(capsys, tmp_path):
    code, out = run_companies(capsys, tmp_path, "add", "lever:Onehouse", "https://jobs.ashbyhq.com/ashby/123")
    assert code == 0 and "✓ Lever" in out and "✓ Ashby" in out and "open listings" in out
    _, out = run_companies(capsys, tmp_path, "list")
    assert "lever:Onehouse" in out and "ashby:ashby" in out
    _, out = run_companies(capsys, tmp_path, "remove", "lever:Onehouse")
    assert "Removed" in out
    assert [board.source for board in JobStore(tmp_path).known_boards()] == ["ashby"]


def test_companies_careers_site_is_saved_as_the_board_behind_it(capsys, tmp_path):
    site = "https://www.test-co.example/careers"
    client = RecordedClient(pages={site: '<a href="https://apply.workable.com/huggingface/">Jobs</a>'})
    code, out = run_companies(capsys, tmp_path, "add", site, client=client)
    assert code == 0 and "workable:huggingface" in out
    assert JobStore(tmp_path).known_boards() == [JobBoard("workable", "huggingface")]


def test_companies_rejects_portals_and_nonsense(capsys, tmp_path):
    code, out = run_companies(capsys, tmp_path, "add", "remotive:backend", "nonsense")
    assert code == 1 and out.count("✗") == 2
    assert JobStore(tmp_path).known_boards() == []


def test_companies_unreachable_board_is_not_saved(capsys, tmp_path):
    code, out = run_companies(capsys, tmp_path, "add", "lever:gone", client=RecordedClient({"gone": "not_found"}))
    assert code == 1 and "not_found" in out
    assert JobStore(tmp_path).known_boards() == []


def scored(score, missing, required=(), reliable=True):
    return {"match_score": score, "missing_skills": list(missing), "missing_required_skills": list(required),
            "reliable": reliable}


def test_skill_gaps_weigh_required_skills_above_mentions():
    jobs = [scored(70, ["Kafka", "Go"], ["Kafka"]), scored(65, ["Kafka", "Go"], ["Kafka"]),
            scored(60, ["Go", "Rust"]), scored(30, ["Kafka"], ["Kafka"]), scored(90, ["Elixir"], ["Elixir"], reliable=False)]
    ranking, counted = skill_gaps.rank_gaps(jobs, 40)
    assert counted == 3
    assert [item["skill"] for item in ranking] == ["Kafka", "Go", "Rust"]
    assert ranking[0] == {"skill": "Kafka", "required_by": 2, "mentioned_by": 0, "weight": 6}


def test_skill_gaps_command_reads_saved_results(capsys, tmp_path):
    write_json(tmp_path / "job_results.json", [scored(70, ["Kafka"], ["Kafka"])])
    assert skill_gaps.run(skill_gaps.parse_arguments(["--data-dir", str(tmp_path)])) == 0
    assert "| Kafka | 1 | 0 |" in capsys.readouterr().out


def test_skill_gaps_without_results_says_what_to_do(capsys, tmp_path):
    assert skill_gaps.run(skill_gaps.parse_arguments(["--data-dir", str(tmp_path)])) == 1
    assert "/job-search" in capsys.readouterr().err
