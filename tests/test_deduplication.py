from conftest import build_job
from deduplicate import deduplicate_jobs, description_similarity, normalize_url, role_key


def test_same_application_url_is_removed():
    jobs = [build_job(job_id="1", url="https://jobs.lever.co/a/1"),
            build_job(job_id="2", title="Other", url="https://JOBS.lever.co/a/1/")]
    unique, removed = deduplicate_jobs(jobs)
    assert len(unique) == 1 and removed["application_url"] == 1


def test_same_job_id_is_removed():
    jobs = [build_job(job_id="1", url="https://jobs.lever.co/a/1"), build_job(job_id="1", title="Other", url="https://jobs.lever.co/a/2")]
    unique, removed = deduplicate_jobs(jobs)
    assert len(unique) == 1 and removed["job_id"] == 1


def test_same_company_title_and_location_is_removed():
    jobs = [build_job(job_id="1", url="https://x/1", title="Senior Engineer!", location="Pune"),
            build_job(job_id="2", url="https://x/2", title="senior engineer", location="PUNE", description="Different text")]
    unique, removed = deduplicate_jobs(jobs)
    assert len(unique) == 1 and removed["company_title_location"] == 1


def test_same_description_in_another_office_is_merged_and_recorded():
    jobs = [build_job(job_id="1", url="https://x/1", title="Java Backend Developer - Pune", location="Pune"),
            build_job(job_id="2", url="https://x/2", title="Java Backend Developer - Vadodara", location="Vadodara")]
    unique, removed = deduplicate_jobs(jobs)
    assert len(unique) == 1 and removed["description_similarity"] == 1
    assert unique[0]["other_locations"] == ["Vadodara"]


def test_different_roles_sharing_boilerplate_are_kept():
    shared = "We are a great company with a mission. " * 30
    jobs = [build_job(job_id="1", url="https://x/1", title="Backend Engineer", description=shared),
            build_job(job_id="2", url="https://x/2", title="Frontend Engineer", description=shared)]
    assert len(deduplicate_jobs(jobs)[0]) == 2


def test_different_levels_are_kept():
    jobs = [build_job(job_id="1", url="https://x/1", title="Engineer - Pune", location="Pune"),
            build_job(job_id="2", url="https://x/2", title="Engineer - Senior", location="Mumbai")]
    assert len(deduplicate_jobs(jobs)[0]) == 2


def test_same_title_at_other_companies_is_kept():
    jobs = [build_job(job_id="1", url="https://x/1", company="Test Co"), build_job(job_id="2", url="https://x/2", company="Other Test Co")]
    assert len(deduplicate_jobs(jobs)[0]) == 2


def test_no_jobs():
    assert deduplicate_jobs([])[0] == []


def test_helpers():
    assert normalize_url("https://Jobs.lever.co/a/1/apply/") == "jobs.lever.co/a/1"
    assert role_key("Java Developer - Pune") == "java developer"
    assert description_similarity("one two three four", "one two three four") == 1.0
    assert description_similarity("", "anything at all here") == 0.0
