import pytest

from location_matching import candidate_targets, countries_in, is_global_location, match_location

PUNE = ["Pune, India"]


def job_at(location, remote=None, description=""):
    return {"location": location, "remote": remote, "description": description}


@pytest.mark.parametrize("location,country", [
    ("Bengaluru", "india"), ("Remote - US", "united_states"), ("San Francisco, CA", "united_states"),
    ("London, UK", "united_kingdom"), ("Riyadh", "saudi_arabia"), ("Bucharest, Romania", "romania"),
])
def test_countries_are_recognised(location, country):
    assert country in countries_in(location)


def test_regions_expand_to_countries():
    assert {"germany", "united_kingdom"} <= countries_in("Remote, EMEA")
    assert "india" in countries_in("APAC")


def test_short_forms_are_case_sensitive():
    assert "united_states" not in countries_in("Join us today")


def test_indiana_is_not_india():
    assert "india" not in countries_in("Indianapolis, Indiana")


@pytest.mark.parametrize("job,status", [
    (job_at("India - Pune"), "match"),
    (job_at("Bengaluru, India"), "partial"),
    (job_at("Berlin, Germany"), "mismatch"),
    (job_at("Remote, India", True), "match"),
    (job_at("India-Remote"), "match"),
    (job_at("Remote", True), "match"),
    (job_at("Worldwide", True), "match"),
    (job_at("Remote - US", True), "mismatch"),
    (job_at("Remote", True, "You must be based in the United States."), "mismatch"),
    (job_at(""), "unknown"),
    (job_at("Atlantis"), "unknown"),
])
def test_location_decisions(job, status):
    assert match_location(job, PUNE).status == status


def test_no_location_to_compare_is_unknown():
    assert match_location(job_at("Pune"), []).status == "unknown"


def test_remote_filter_keeps_the_candidates_country(profile):
    targets = candidate_targets(profile, {}, "Remote")
    assert targets == ["Remote", "Pune, India"]
    assert match_location(job_at("Remote, Germany", True), targets).status == "mismatch"


def test_explicit_filter_beats_saved_preferences(profile):
    assert candidate_targets(profile, {"target_locations": ["Pune"]}, "Bangalore") == ["Bangalore"]


def test_saved_preferences_beat_the_resume(profile):
    assert candidate_targets(profile, {"target_locations": ["Hyderabad"]}) == ["Hyderabad"]


def test_global_terms():
    assert is_global_location("Work from anywhere")
