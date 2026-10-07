from pathlib import Path

import pytest

from job_agent.config import CompanyConfig, load_config
from job_agent.title_filter import TitleFilter

REPO_CONFIG = load_config(Path(__file__).parent.parent / "companies.yaml")
TITLES = REPO_CONFIG.title_filter


def test_real_fixture_titles(adyen_jobs, nebius_jobs, nebius_location_jobs):
    got = {j.title: TITLES.seniority(j.title)
           for j in adyen_jobs + nebius_jobs + nebius_location_jobs}
    assert got == {
        "Account Manager": "manager",
        "Account Executive, Digital Native": None,
        "Account Executive - South Korea": None,
        "Administrative Services Manager": "manager",
        "AI Science Writer, Nebius Academy (Contract)": None,
        "Senior Data Engineer": "senior",
        "Technical Program Manager - New Data Center Launches": "manager",
        "Application Integration Developer": None,
        "Head of Employee Relations": "head of",
    }


# Real titles from jobs.db, plus synthetic shapes for false-positive checks.
@pytest.mark.parametrize("title, expected", [
    ("Sr. HR Business Partner", "sr"),
    ("Senior/Staff Application Security Engineer", "senior"),
    ("Staff / Principal Applied AI Researcher (Agentic Search)", "staff"),
    ("Engineering Manager/Network Team Lead", "manager"),
    ("Group Product Manager, APAC [Head of Products, APAC]", "manager"),
    ("Head  of Engineering", "head of"),             # any whitespace inside a phrase
    ("Federal Affairs Leader", "leader"),
    ("Vice President of Product Management", "vice president"),
    ("VP, Engineering", "vp"),
    ("Chief of Staff", "chief"),
    ("Principal, EMEA GTM - Physical AI", "principal"),
    ("Senior Member of Technical Staff", "senior"),  # exception removes only the phrase
    ("Staff Engineer - Member of Technical Staff", "staff"),
    # False positives: keywords inside other words, or exempted phrases.
    ("Member of Technical Staff", None),
    ("member  of technical STAFF", None),
    ("Senior Site Reliability Engineer (SRE)", "senior"),
    ("Site Reliability Engineer (SRE)", None),
    ("Internal Control Specialist, Technology Risk", None),
    ("Leadership Development Analyst", None),
    ("Staffing Coordinator", None),
    ("Headless CMS Engineer", None),
    ("Head Chef", None),                             # "head" alone is not "head of"
    ("Mischief Analyst", None),
    ("Data Engineer", None),
])
def test_seniority(title, expected):
    assert TITLES.seniority(title) == expected


@pytest.mark.parametrize("title, expected", [
    ("Software Engineering Intern", True),
    ("Internship - Data Science", True),
    ("Graduate Software Engineer", True),
    ("Finance Trainee", True),
    ("Working Student Data Engineering", True),
    ("Werkstudent Backend (m/w/d)", True),
    ("Afstudeerstage Payments", True),
    ("Stage Data Analyse (m/v)", True),
    ("Stage bij het Data team", True),
    ("Stagiair Software Engineering - stage", True),
    # False positives.
    ("Early-Stage Sales Lead", False),
    ("Multi-stage Pipeline Engineer", False),
    ("Stage Manager, Events", False),
    ("Backstage Engineer", False),
    ("Internal Control Specialist", False),
    ("Internationalization Engineer", False),
    ("Postgraduate Research Scientist", False),
    ("International Payments Analyst", False),
    ("Data Engineer", False),
])
def test_is_internship(title, expected):
    assert TITLES.is_internship(title) is expected


@pytest.mark.parametrize("kwargs, message", [
    ({"exclude_seniority": []}, "exclude_seniority must not be empty"),
    ({"exclude_seniority": "senior"}, "exclude_seniority must be a list"),
    ({"exclude_seniority": ["senior", " "]}, "non-empty strings"),
    ({"exclude_seniority": ["senior"], "exceptions": [None]}, "non-empty strings"),
    ({"exclude_seniority": ["senior"], "internship": "intern"}, "internship must be a list"),
    ({"exclude_seniority": ["senior"], "internship_dutch": [""]}, "non-empty strings"),
])
def test_invalid_title_filter_raises(kwargs, message):
    with pytest.raises(ValueError, match=message):
        TitleFilter(**kwargs)


def test_without_internship_keywords_nothing_is_internship():
    titles = TitleFilter(exclude_seniority=["senior"])
    assert not titles.is_internship("Software Engineering Intern")
    assert not titles.is_internship("Stage bij het Data team")


def test_dutch_keywords_need_a_cue():
    titles = TitleFilter(exclude_seniority=["senior"], internship_dutch=["stage"])
    assert titles.is_internship("Stage Data (m/v)")
    assert not titles.is_internship("Stage Data")


def test_config_rejects_unknown_title_filter_keys(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("title_filter:\n  exclude_seniority: [senior]\n  exception: [x]\n")
    with pytest.raises(ValueError, match="unknown keys"):
        load_config(path)


def test_exclude_categories_case_insensitive_exact():
    company = CompanyConfig(name="x", source="greenhouse", board_token="x",
                            exclude_categories=["Sales", " Legal "])
    assert company.excludes_category("sales")
    assert company.excludes_category("Legal")
    assert not company.excludes_category("Sales Engineering")
    assert not company.excludes_category(None)


@pytest.mark.parametrize("value", ["Sales", ["Sales", ""], [1]])
def test_invalid_exclude_categories_names_company(value):
    with pytest.raises(ValueError, match="^acme: exclude_categories"):
        CompanyConfig(name="acme", source="greenhouse", board_token="acme",
                      exclude_categories=value)


def test_repo_config_excludes_known_categories():
    nebius = REPO_CONFIG.company("nebius")
    assert nebius.excludes_category("Government Relations")
    # Restored: it holds software and SRE roles in Amsterdam.
    assert not nebius.excludes_category("Hardware Infrastructure")
    assert not nebius.excludes_category("Product")
    adyen = REPO_CONFIG.company("adyen")
    assert adyen.excludes_category("Strategy & Execution")
    assert not adyen.excludes_category("Professional Services")
