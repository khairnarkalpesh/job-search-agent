"""The whole run, with the network replaced by recorded real responses or by failures."""
import json

import pytest

import search_jobs
from conftest import FIXTURES, RecordedClient, build_job
from job_storage import read_json
from results_report import format_job_details, format_results_table
from score_jobs import score_job

RESUME = str(FIXTURES / "synthetic_resume.md")


@pytest.fixture
def run_cli(monkeypatch, tmp_path, capsys):
    def run(*extra_arguments, client=None):
        monkeypatch.setattr(search_jobs, "HttpClient", lambda **_: client or RecordedClient())
        monkeypatch.setattr(search_jobs, "load_preferences", lambda: {})
        arguments = search_jobs.parse_arguments(["--resume", RESUME, "--data-dir", str(tmp_path), *extra_arguments])
        return search_jobs.run(arguments), capsys.readouterr()
    return run


# Most tests pin the two original sources so that board counts are predictable.
BOARDS = ("--board", "greenhouse:capco", "--board", "lever:Onehouse", "--source", "greenhouse,lever")


def test_full_run_on_real_recorded_listings(run_cli, tmp_path):
    code, output = run_cli(*BOARDS, "--all")
    assert code == 0
    assert "Analyzing your profile" in output.out
    assert "TOP MATCHES" in output.out
    stored = read_json(tmp_path / "job_results.json", [])
    assert stored
    for job in stored:
        assert job["url"].startswith("https://")
        assert job["score_breakdown"]["skills"]["detail"]
        assert job["why_match"]


def test_every_shown_job_links_to_its_original_listing(run_cli):
    _, output = run_cli(*BOARDS, "--all")
    assert "Listing on Greenhouse: https://" in output.out or "Listing on Lever: https://" in output.out


def test_second_run_marks_jobs_as_seen(run_cli, tmp_path):
    run_cli(*BOARDS, "--all")
    _, output = run_cli(*BOARDS, "--all")
    assert "PREVIOUSLY SEEN" in output.out and "NEW JOB" not in output.out


def test_new_only_hides_seen_jobs(run_cli):
    run_cli(*BOARDS, "--all")
    _, output = run_cli(*BOARDS, "--all", "--new-only")
    assert "PREVIOUSLY SEEN" not in output.out


def test_boards_are_reused_without_being_named_again(run_cli):
    run_cli(*BOARDS, "--all")
    code, output = run_cli("--all", "--source", "greenhouse,lever")
    assert code == 0 and "TOP MATCHES" in output.out


def test_min_score_filters_results(run_cli):
    code, output = run_cli(*BOARDS, "--min-score", "101")
    assert code == 0
    assert "No jobs reached the minimum score of 101" in output.out


def test_limit_caps_results(run_cli):
    _, output = run_cli(*BOARDS, "--all", "--limit", "1")
    table_rows = [line for line in output.out.splitlines() if line.startswith("| ") and "Score" not in line]
    assert len(table_rows) == 1


def test_source_filter_skips_other_boards(run_cli, tmp_path):
    run_cli(*BOARDS, "--source", "lever", "--all")
    assert {job["source"] for job in read_json(tmp_path / "job_results.json", [])} == {"lever"}


def test_one_failing_board_does_not_stop_the_run(run_cli):
    code, output = run_cli(*BOARDS, "--all", client=RecordedClient({"Onehouse": "blocked"}))
    assert code == 0
    assert "Skipped lever/Onehouse: source unavailable (blocked)" in output.out
    assert "TOP MATCHES" in output.out


def test_every_board_failing_is_reported(run_cli):
    code, output = run_cli(*BOARDS, client=RecordedClient({"capco": "network", "Onehouse": "not_found"}))
    assert code == 1
    assert "No listings were available" in output.out


def test_boards_with_no_listings_are_reported(run_cli):
    code, output = run_cli(*BOARDS, client=RecordedClient(empty=True))
    assert code == 1
    assert "no open listings" in output.out


def test_no_boards_and_blocked_search_gives_next_step(run_cli):
    code, output = run_cli("--source", "greenhouse,lever")
    assert code == 1
    assert "Web search unavailable" in output.out
    assert "--board" in output.out


def test_unreadable_resume_exits_cleanly(monkeypatch, tmp_path, capsys):
    arguments = search_jobs.parse_arguments(["--resume", str(tmp_path / "none.pdf"), "--data-dir", str(tmp_path)])
    assert search_jobs.run(arguments) == 2
    assert "not found" in capsys.readouterr().err


def test_plan_prints_queries_without_touching_the_network(run_cli):
    code, output = run_cli("--plan")
    queries = json.loads(output.out[output.out.index("["):])
    assert code == 0 and queries


def test_synthetic_resume_stays_out_of_real_data(monkeypatch):
    arguments = search_jobs.parse_arguments(["--resume", RESUME])
    assert search_jobs.choose_data_dir(arguments, {"synthetic": True}) == search_jobs.SYNTHETIC_DATA_DIR
    arguments = search_jobs.parse_arguments(["--resume", RESUME, "--data-dir", str(search_jobs.DATA_DIR)])
    assert search_jobs.choose_data_dir(arguments, {"synthetic": True}) == search_jobs.SYNTHETIC_DATA_DIR


def test_real_resume_uses_real_data_dir():
    assert search_jobs.choose_data_dir(search_jobs.parse_arguments([]), {"synthetic": False}) == search_jobs.DATA_DIR


def test_bad_board_argument_is_rejected():
    with pytest.raises(SystemExit):
        search_jobs.parse_board_argument("nonsense")


def test_unknown_source_is_rejected():
    with pytest.raises(SystemExit):
        search_jobs.choose_sources(search_jobs.parse_arguments(["--source", "indeed"]), {})


def test_preferences_given_on_a_run_are_saved_without_inventing_others(monkeypatch):
    saved = {}
    monkeypatch.setattr(search_jobs, "save_preferences", saved.update)
    arguments = search_jobs.parse_arguments(["--location", "Remote,Pune", "--min-score", "80"])
    search_jobs.persist_preferences(arguments, {"employment_types": ["full_time"]}, ["greenhouse", "lever"])
    assert saved == {"employment_types": ["full_time"], "target_locations": ["Remote", "Pune"], "minimum_match_score": 80}


def make_arguments(*values):
    return search_jobs.parse_arguments(list(values))


def test_relevance_filter_keeps_targets_and_drops_the_rest(profile):
    families = search_jobs.allowed_role_families(profile, {}, "")
    targets = ["Pune, India"]
    keep = lambda title: search_jobs.is_relevant(build_job(title=title), families, make_arguments(), targets, {})
    assert keep("Senior Java Developer")
    assert keep("Software Engineer")
    assert not keep("Account Executive")
    assert not keep("Mechanical Engineer")
    assert not keep("Engineering Manager")
    assert not keep("iOS Developer")


def test_remote_filter(profile):
    families = search_jobs.allowed_role_families(profile, {}, "")
    relevant = lambda job: search_jobs.is_relevant(job, families, make_arguments("--remote"), [], {})
    assert relevant(build_job(location="Remote, India"))
    assert not relevant(build_job(location="Pune, India"))


def test_location_filter(profile):
    families = search_jobs.allowed_role_families(profile, {}, "")
    relevant = lambda job: search_jobs.is_relevant(job, families, make_arguments("--location", "Bangalore"), ["Bangalore"], {})
    assert relevant(build_job(location="Bangalore, India"))
    assert not relevant(build_job(location="Berlin, Germany"))


def test_employment_preference_filter(profile):
    families = search_jobs.allowed_role_families(profile, {}, "")
    job = build_job(employment_type="contract")
    assert not search_jobs.is_relevant(job, families, make_arguments(), [], {"employment_types": ["full_time"]})


def test_report_includes_score_breakdown_and_gaps(profile):
    job = score_job(build_job(), profile)
    job["seen"] = "NEW JOB"
    assert "Skills" in format_job_details(job, 1) and "Why it matches" in format_job_details(job, 1)
    assert job["title"] in format_results_table([job])


ALL_COMPANY_BOARDS = ("--board", "greenhouse:capco", "--board", "lever:Onehouse", "--board", "ashby:ashby",
                      "--board", "workable:huggingface", "--board", "smartrecruiters:BoschGroup")


def test_default_run_reads_every_source(run_cli, tmp_path):
    client = RecordedClient()
    code, output = run_cli(*ALL_COMPANY_BOARDS, "--all", client=client)
    assert code == 0
    for label in ("Greenhouse", "Lever", "Ashby", "Workable", "SmartRecruiters", "Remotive", "Remote OK", "Himalayas", "Arbeitnow"):
        assert label in output.out
    assert {"remotive", "remoteok", "himalayas", "lever", "ashby"} <= {job["source"] for job in read_json(tmp_path / "job_results.json", [])}


def test_portals_are_searched_by_target_role_not_saved_as_companies(run_cli, tmp_path):
    client = RecordedClient()
    run_cli("--source", "remotive", "--role", "Backend Engineer", "--all", client=client)
    assert any("remotive.com" in url and "Backend+Engineer" in url for url in client.requested)
    assert read_json(tmp_path / "known_boards.json", []) == []


def test_smartrecruiters_descriptions_are_fetched_only_for_relevant_jobs(run_cli, tmp_path):
    client = RecordedClient()
    run_cli("--board", "smartrecruiters:BoschGroup", "--source", "smartrecruiters", "--all", client=client)
    detail_calls = [url for url in client.requested if "/postings/" in url]
    # Neither recorded posting is a role this resume targets, so no detail call is needed.
    assert len(detail_calls) == len(read_json(tmp_path / "job_results.json", []))
