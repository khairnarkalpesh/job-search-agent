import pytest

from skill_taxonomy import classify_skill, find_skills, seniority_from_title, title_family

JAVA_CANDIDATE = {"Java", "Spring Boot", "PostgreSQL", "React", "AWS", "Docker"}


@pytest.mark.parametrize("job_skill,expected", [
    ("Java", "EXACT"),
    ("Spring Boot", "EXACT"),
    ("Spring Framework", "RELATED"),
    ("MySQL", "RELATED"),
    ("JavaScript", "RELATED"),
    ("Kotlin", "RELATED"),
    ("Scala", "TRANSFERABLE"),
    ("GCP", "TRANSFERABLE"),
    ("Kubernetes", "TRANSFERABLE"),
    ("Node.js", "MISSING"),
    ("Go", "MISSING"),
    ("Python", "MISSING"),
])
def test_skill_classification(job_skill, expected):
    assert classify_skill(job_skill, JAVA_CANDIDATE)[0] == expected


def test_skill_match_names_the_skill_that_justifies_it():
    assert classify_skill("Spring Framework", JAVA_CANDIDATE) == ("RELATED", "Spring Boot")


@pytest.mark.parametrize("text,present,absent", [
    ("Strong JavaScript skills", ["JavaScript"], ["Java"]),
    ("We use Java.", ["Java"], ["JavaScript"]),
    ("C++ and C# required", ["C++", "C#"], []),
    ("Python/Django services", ["Python", "Django"], []),
    ("Built in Golang", ["Go"], []),
    ("Our go to market team will go beyond", [], ["Go"]),
    ("Go services at scale", ["Go"], []),
    ("REST APIs", ["REST APIs"], []),
    ("rest of the team", [], ["REST APIs"]),
    ("k8s and Postgres", ["Kubernetes", "PostgreSQL"], []),
    ("React Native apps", ["React Native"], []),
    ("We react quickly", [], ["React"]),
    ("It will spark ideas", [], ["Apache Spark"]),
])
def test_skill_detection(text, present, absent):
    found = find_skills(text)
    assert set(present) <= set(found)
    assert not set(absent) & set(found)


@pytest.mark.parametrize("title,family", [
    ("Senior Backend Engineer", "backend"),
    ("Java Developer", "backend"),
    ("Full Stack Engineer", "fullstack"),
    ("Software Engineer II", "general_software"),
    ("Sr Software Development Engineer - Testing", "qa"),
    ("Senior Lead Quality Engineer", "qa"),
    ("Machine Learning Engineer", "ml_ai"),
    ("Mechanical Engineer", "other_engineering"),
    ("Sales Engineer", "not_engineering"),
    ("Engineering Manager, Payments", "management"),
    ("Senior Engineer, Sourcing Development, Footwear", "unspecified_engineer"),
    ("Administrative Business Partner", "not_engineering"),
])
def test_title_family(title, family):
    assert title_family(title) == family


@pytest.mark.parametrize("title,level", [
    ("Senior Software Engineer", "senior"), ("Sr. Developer", "senior"), ("Staff Engineer", "staff"),
    ("Principal Engineer", "principal"), ("Junior Developer", "junior"), ("Software Engineer Intern", "intern"),
    ("Software Engineer II", "mid"), ("Software Engineer", ""),
])
def test_seniority_from_title(title, level):
    assert seniority_from_title(title) == level
