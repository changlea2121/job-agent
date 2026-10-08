from dataclasses import replace

import pytest

from job_agent.config import load_config
from job_agent.experience import ExperienceFilter, mentions, required_years
from job_agent.filtering import apply_filters


# Real lines from jobs.db unless marked "made up". Dutch phrasing and degree
# alternatives do not occur in the stored postings yet.
@pytest.mark.parametrize("text, expected", [
    ("- 5+ years of professional software engineering experience", 5),
    ("- You possess at least 4 years of relevant working experience in an analytical "
     "or business-focused environment.", 4),
    ("- Typically 5 or more years of electrical design experience in data centers", 5),
    ("- 3+ years administering Microsoft Entra ID in production as a primary "
     "responsibility.", 3),  # no "experience" in the line
    ("- At least five years of professional software engineering experience", 5),  # made up
    ("- A minimum of 4 years of experience with Java", 4),  # made up
    # Ranges: the lower bound.
    ("- 1-2+ years of experience in fraud or AML at a financial institution", 1),
    ("- You have 3-4 years of experience in a client-facing/commercial role", 3),
    ("- 7–10 years of public affairs, communications and/or community engagement work", 7),
    ("You apply focus and drive change, and have between 2-6 years of experience "
     "directly managing technical support teams.", 2),
    # Several numbers: the highest blocking one.
    ("- 10+ years of engineering experience, including 5+ years as a leader", 10),
    ("- 5+ years of software engineering experience\n- 2+ years with Kubernetes", 5),
    # Still blocking: "or equivalent" is not a degree.
    ("- 5+ years of professional software engineering experience (or equivalent "
     "practical background)", 5),
    # Softeners apply to the domain here, not to the years.
    ("- 10+ years of product experience ideally within Platform Engineering", 10),
    ("- You have 3+ years of experience in operational Accounting, Accounts Payable "
     "experience is a plus", 3),
    # Dutch (made up).
    ("- Minimaal 3 jaar werkervaring als developer", 3),
    ("- Je hebt drie jaar ervaring met Java", 3),
    ("- 2 tot 4 jaar ervaring", 2),
])
def test_required_years(text, expected):
    assert required_years(text) == expected


@pytest.mark.parametrize("text", [
    # Timeframes and company history (real).
    "- Set the Vision: developing short-term (1 year), medium-term (1-3 years), and "
    "long-term (3-5 years) support strategies",
    "- Professional Engineering (PE) license or ability to obtain one within 2 years.",
    "In less than two years, we have brought up and operated large GPU clusters.",
    "20 years of payments data is a powerful asset.",
    # Softened (made up, except the heading, which nebius uses).
    "- Ideally 4+ years of backend experience",
    "- 5+ years of Kubernetes experience is a plus",
    "It will be an added bonus if you have:\n- 5+ years of Go experience",
    "Nice to have:\n- 5+ years of Go experience",
    # A non-PhD degree can replace the years (made up).
    "- 3+ years of experience or a Master's degree in CS",
    "- 3+ years of experience, or an MSc in Computer Science",
    "- A Bachelor's degree or 3+ years of experience",
    "- 5+ years of experience or a Master's or PhD",
    "- Minimaal 3 jaar werkervaring of een afgeronde master",
    # No years at all.
    "- Deep experience with Python and highly skilled in distributed systems",
])
def test_no_blocking_requirement(text):
    assert required_years(text) is None


@pytest.mark.parametrize("text, expected", [
    # A PhD-only alternative still blocks.
    ("- 5+ years of experience or a PhD", 5),
    ("- 5+ years of experience or a PhD degree in ML", 5),
    # The degree is an extra requirement, not an alternative.
    ("- 5+ years of experience with Java or Kotlin, and a degree in CS", 5),
    ("- Bachelor's degree in CS or related field, and 5+ years of experience", 5),
    ("- 3+ years of experience with a degree in CS", 3),
])
def test_degree_that_is_not_an_alternative(text, expected):
    assert required_years(text) == expected


def test_section_resets_after_next_heading():
    text = ("Nice to have:\n- 5+ years of Go experience\n"
            "Requirements:\n- 4+ years of Python experience")
    assert [(m.years, m.optional) for m in mentions(text)] == [(5, True), (4, False)]


def test_filter_threshold():
    rule = ExperienceFilter(min_years=3)
    assert rule.excluded_years("- 3+ years of experience") == 3
    assert rule.excluded_years("- 2+ years of experience") is None
    assert rule.excluded_years("- 1-3 years of experience") is None
    assert rule.excluded_years("no years") is None
    assert ExperienceFilter().min_years == 3


@pytest.mark.parametrize("value", [0, -1, "3", 2.5, True])
def test_invalid_min_years(value):
    with pytest.raises(ValueError, match="min_years must be a positive integer"):
        ExperienceFilter(min_years=value)


def test_config_section(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("companies: []\nexperience_filter: {min_years: 4}\n")
    assert load_config(path).experience_filter == ExperienceFilter(4)
    path.write_text("companies: []\n")
    assert load_config(path).experience_filter is None
    path.write_text("companies: []\nexperience_filter: {years: 4}\n")
    with pytest.raises(ValueError, match="unknown keys"):
        load_config(path)


def test_rule_runs_after_title_rules(tmp_path, nebius_location_jobs):
    writer = nebius_location_jobs[0]  # Amsterdam, no years in its description
    senior = replace(writer, source_id="x1", title="Senior Engineer",
                     description="- 5+ years of experience")
    needs_years = replace(writer, source_id="x2", description="- 5+ years of experience")
    intern = replace(writer, source_id="x3", title="Data Intern",
                     description="- 3+ years of experience")
    path = tmp_path / "c.yaml"
    path.write_text("companies: []\n"
                    "title_filter: {exclude_seniority: [senior], internship: [intern]}\n"
                    "experience_filter: {min_years: 3}\n")
    result = apply_filters([writer, senior, needs_years, intern], load_config(path))
    assert result.jobs == [writer]
    assert result.internships == []  # the rule applies to internships too
    assert [(j.source_id, rule, detail) for j, rule, detail in result.excluded] == [
        ("x1", "seniority", "senior"),
        ("x2", "experience", "5+ years"),
        ("x3", "experience", "3+ years"),
    ]
