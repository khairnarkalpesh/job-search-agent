import pytest

from conftest import build_job
from normalize_jobs import detect_remote, enrich_job, extract_salary, html_to_text, make_job, split_sections


def test_double_escaped_html_becomes_plain_text():
    text = html_to_text("&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Java&lt;/li&gt;&lt;/ul&gt;&lt;script&gt;x()&lt;/script&gt;")
    assert "Build & ship" in text
    assert "- Java" in text
    assert "x()" not in text


def test_requirements_and_preferences_are_separated():
    text = "About us\nWe ship.\nRequirements\n- Java\n- SQL\nNice to have\n- Kafka\nBenefits\n- Lunch"
    requirements, preferred = split_sections(text)
    assert requirements == ["Java", "SQL"]
    assert preferred == ["Kafka"]


def test_listing_without_headings_falls_back_to_requirement_sentences():
    requirements, _ = split_sections("We want people.\nYou must have Java.\n3+ years building services.")
    assert requirements == ["You must have Java.", "3+ years building services."]


@pytest.mark.parametrize("text,expected", [
    ("Base salary: $120,000 - $150,000 USD per year", "$120,000 - $150,000 USD"),
    ("Compensation: ₹25,00,000 to ₹35,00,000", "₹25,00,000 to ₹35,00,000"),
    ("Salary range £60k-£80k", "£60k-£80k"),
    ("The pay range is $92,000 to $130,000, plus equity", "$92,000 to $130,000"),
    ("We raised $35M in Series B funding", ""),
    ("Annual revenue of $475M", ""),
    ("Join a company valued at $1 billion", ""),
    ("Lunch budget of $25", ""),
    ("A $50,000 signing bonus", ""),
    ("No figures here", ""),
])
def test_salary_is_only_a_listed_pay_figure(text, expected):
    assert extract_salary(text) == expected


@pytest.mark.parametrize("location,workplace,expected", [
    ("Remote, India", "", True), ("India", "remote", True), ("Pune", "hybrid", False),
    ("Pune (Hybrid)", "", False), ("Pune", "onsite", False), ("Pune", "", None), ("", "", None),
])
def test_remote_detection(location, workplace, expected):
    assert detect_remote(location, workplace) is expected


def test_missing_fields_stay_empty():
    job = enrich_job(make_job(source="lever", job_id="1", title="Engineer", company="", location="", description="", url="https://x/1"))
    assert job["company"] == "" and job["location"] == "" and job["salary"] == ""
    assert job["remote"] is None and job["requirements"] == [] and job["technologies"] == []


def test_title_whitespace_is_cleaned():
    assert build_job(title="  Senior   Engineer \n")["title"] == "Senior Engineer"


def test_double_encoded_text_from_a_source_is_repaired():
    from normalize_jobs import repair_mojibake
    assert repair_mojibake("Ciudad de MÃ©xico") == "Ciudad de México"
    assert repair_mojibake("CafÃ© â€“ Remote") == "Café – Remote"
    assert repair_mojibake("Ciudad de México") == "Ciudad de México"
    assert repair_mojibake("Ã alone") == "Ã alone"
