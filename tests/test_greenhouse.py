from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_fixture
from job_agent.config import CompanyConfig
from job_agent.html_text import html_to_text
from job_agent.sources.greenhouse import GreenhouseAdapter


def test_maps_core_fields(nebius_jobs):
    job = nebius_jobs[0]
    assert job.source == "greenhouse"
    assert job.company == "nebius"
    assert job.source_id == "4959063101"
    assert job.title == "Account Executive, Digital Native"
    assert job.location == "United States"
    assert job.url == "https://careers.nebius.com/?gh_jid=4959063101"


def test_first_published_is_used_not_updated_at(nebius_jobs):
    # Fixture has first_published 2026-08-25 and updated_at 2026-10-02.
    expected = datetime(2026, 8, 25, 8, 2, 7, tzinfo=timezone(timedelta(hours=-4)))
    assert nebius_jobs[0].first_published == expected
    assert nebius_jobs[0].first_published.tzinfo is not None


def test_description_is_plain_text(adyen_jobs, nebius_jobs):
    for job in adyen_jobs + nebius_jobs:
        assert job.description
        assert "<" not in job.description and "&lt;" not in job.description
        assert "&amp;" not in job.description
    assert "This is Adyen" in adyen_jobs[0].description
    assert "H&M" in adyen_jobs[0].description


def test_title_whitespace_is_stripped(adyen_jobs):
    assert adyen_jobs[0].title == "Account Manager"  # raw title is " Account Manager"


def test_category_from_configured_metadata_field(nebius_jobs):
    assert nebius_jobs[0].category == "Sales"


def test_category_none_when_field_missing_on_job(nebius_jobs):
    # Fixture job 3 was hand-edited to have empty metadata.
    assert nebius_jobs[2].category is None


def test_category_from_departments(adyen_jobs):
    # adyen fixture: metadata is null, departments = [{"name": "Account Management", ...}]
    assert [j.category for j in adyen_jobs] == ["Account Management"] * 3


def test_category_none_when_not_configured():
    company = CompanyConfig("adyen", "greenhouse", "adyen")
    jobs = GreenhouseAdapter(company).parse(load_fixture("greenhouse_adyen.json"))
    assert all(j.category is None for j in jobs)


def _job_payload(**extra):
    return {"jobs": [{
        "id": 1, "title": "Eng", "absolute_url": "u", "location": {"name": "X"},
        "content": "", "first_published": None, **extra,
    }]}


def test_category_metadata_field_is_configurable():
    payload = _job_payload(metadata=[
        {"name": "Job Category", "value": "Sales"},
        {"name": "Team", "value": ["Infra", "ML"]},
    ])
    company = CompanyConfig("acme", "greenhouse", "acme", category_metadata_field="Team")
    [job] = GreenhouseAdapter(company).parse(payload)
    assert job.category == "Infra, ML"


def test_multiple_departments_are_joined():
    payload = _job_payload(departments=[{"name": "Engineering"}, {"name": "Data"}])
    company = CompanyConfig("acme", "greenhouse", "acme", category_from="departments")
    [job] = GreenhouseAdapter(company).parse(payload)
    assert job.category == "Engineering, Data"


@pytest.mark.parametrize("kwargs", [
    {"category_from": "metadata"},  # missing field name
    {"category_from": "offices"},   # unknown source
])
def test_invalid_category_config_rejected(kwargs):
    with pytest.raises(ValueError):
        CompanyConfig("acme", "greenhouse", "acme", **kwargs)


def test_html_to_text_handles_escaped_markup():
    raw = "&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;ul&gt;&lt;li&gt;One&lt;/li&gt;&lt;li&gt;Two&lt;/li&gt;&lt;/ul&gt;"
    assert html_to_text(raw) == "Hello & welcome\n\n- One\n\n- Two"
