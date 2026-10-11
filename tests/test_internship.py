from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_agent.config import Config, load_config
from job_agent.filtering import apply_filters
from job_agent.internship import InternshipFilter
from job_agent.models import Job
from job_agent.title_filter import TitleFilter

REPO_CONFIG = load_config(Path(__file__).parent.parent / "companies.yaml")
RULE = REPO_CONFIG.internship_filter


# Real lines from ING and KPN internship postings.
@pytest.mark.parametrize("description, excluded", [
    ("- Student of Computer Science, Software Engineering, IT, Data Analytics, "
     "or related field.", False),
    ("- Je volgt een HBO- of WO-opleiding, bijvoorbeeld Data Science, Business Analytics, "
     "Economie of Finance.", False),  # data science among accepted studies
    ("Final-year Bachelor's or Master's student in Engineering", False),
    ("Je studeert Communicatie, Journalistiek of een vergelijkbare opleiding.", True),
    ("Je volgt een hbo-opleiding ICT en hebt affiniteit met servicedesk werk.", True),
    ("Masterstudent Kunstmatige Intelligentie of Informatica", False),  # made up
    ("Experience with softwareontwikkeling", True),  # whole words only (made up)
])
def test_repo_keywords(description, excluded):
    assert RULE.excludes(description) is excluded


@pytest.mark.parametrize("value, message", [
    ([], "must not be empty"),
    ("software", "must be a list"),
    (["software", ""], "non-empty strings"),
])
def test_invalid_keywords(value, message):
    with pytest.raises(ValueError, match=message):
        InternshipFilter(require_description=value)


def test_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("internship_filter:\n  require: [software]\n")
    with pytest.raises(ValueError, match="unknown keys"):
        load_config(path)


def _job(title, description):
    return Job("greenhouse", "acme", title, title, "Amsterdam", "u", description, None,
               datetime(2026, 10, 1, tzinfo=timezone.utc))


def test_applies_to_internships_only():
    config = Config(
        companies=[], location_filter=None,
        title_filter=TitleFilter(exclude_seniority=["senior"], internship=["intern"]),
        internship_filter=InternshipFilter(require_description=["software"]),
    )
    cs = _job("Software Intern", "Study software engineering")
    marketing = _job("Marketing Intern", "Study communication")
    regular = _job("Marketing Analyst", "Study communication")
    result = apply_filters([cs, marketing, regular], config)
    assert result.internships == [cs]
    assert result.jobs == [regular]
    assert result.excluded == [(marketing, "internship", "no CS/data/AI keyword")]
