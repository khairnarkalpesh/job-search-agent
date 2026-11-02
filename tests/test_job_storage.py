from conftest import build_job
from job_storage import SEEN_BEFORE, SEEN_NEW, JobStore, load_preferences, read_json, save_preferences, write_json
from score_jobs import score_job
from sources import JobBoard


def test_first_sighting_is_new_then_previously_seen(profile, tmp_path):
    store = JobStore(tmp_path)
    first = score_job(build_job(), profile)
    store.record_results([first], {})
    assert first["seen"] == SEEN_NEW and first["status"] == "new"

    second = score_job(build_job(), profile)
    store.record_results([second], {})
    assert second["seen"] == SEEN_BEFORE
    assert second["previous_score"] == first["match_score"]


def test_history_tracks_each_job(profile, tmp_path):
    store = JobStore(tmp_path)
    store.record_results([score_job(build_job(), profile)], {"scored": 1})
    history = read_json(store.history_path, {})
    entry = history["jobs"]["lever:test-co:1"]
    assert set(entry) >= {"url", "job_id", "date_first_discovered", "date_last_seen", "previous_score", "status"}
    assert history["runs"][0]["scored"] == 1


def test_status_set_by_the_user_survives_a_later_search(profile, tmp_path):
    store = JobStore(tmp_path)
    store.record_results([score_job(build_job(), profile)], {})
    history = read_json(store.history_path, {})
    history["jobs"]["lever:test-co:1"]["status"] = "rejected"
    write_json(store.history_path, history)

    job = score_job(build_job(), profile)
    store.record_results([job], {})
    assert job["status"] == "rejected"


def test_jobs_missing_from_a_later_run_stay_on_file(profile, tmp_path):
    store = JobStore(tmp_path)
    store.record_results([score_job(build_job(job_id="1"), profile)], {})
    store.record_results([score_job(build_job(job_id="2"), profile)], {})
    assert len(read_json(store.results_path, [])) == 2


def test_results_are_sorted_by_score(profile, tmp_path):
    store = JobStore(tmp_path)
    weak = score_job(build_job(job_id="1", title="Ruby Developer", description="Requirements\n- Ruby on Rails\n" + "x " * 200), profile)
    strong = score_job(build_job(job_id="2"), profile)
    store.record_results([weak, strong], {})
    assert [job["job_id"] for job in read_json(store.results_path, [])] == [strong["job_id"], weak["job_id"]]


def test_boards_are_remembered_except_one_off_pages(tmp_path):
    store = JobStore(tmp_path)
    store.remember_boards([JobBoard("lever", "acme"), JobBoard("generic", "https://example.com/job")])
    store.remember_boards([JobBoard("lever", "acme"), JobBoard("greenhouse", "other")])
    assert sorted(board.slug for board in store.known_boards()) == ["acme", "other"]


def test_preferences_round_trip(tmp_path):
    path = tmp_path / "preferences.yaml"
    save_preferences({"target_locations": ["Pune"], "minimum_match_score": 80}, path)
    assert load_preferences(path) == {"target_locations": ["Pune"], "minimum_match_score": 80}


def test_missing_files_give_defaults(tmp_path):
    assert load_preferences(tmp_path / "none.yaml") == {}
    assert JobStore(tmp_path).load_profile() is None
    assert JobStore(tmp_path).known_boards() == []

