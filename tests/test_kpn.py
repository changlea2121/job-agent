from datetime import datetime, timedelta, timezone

import pytest

from conftest import FIXTURES, load_fixture
from job_agent.config import CompanyConfig
from job_agent.sources.kpn import KpnAdapter

KPN = CompanyConfig(name="kpn", source="kpn", base_url="https://jobs.kpn.com",
                    category_from="expertise")


def _payload():
    return {"api": load_fixture("kpn_api.json"),
            "rss": (FIXTURES / "kpn_rss.xml").read_text(encoding="utf-8")}


@pytest.fixture
def kpn_jobs():
    return KpnAdapter(KPN).parse(_payload())


def test_joins_rss_and_api(kpn_jobs):
    job = next(j for j in kpn_jobs if j.title == "AI Engineer")
    assert job.source == "kpn"
    assert job.company == "kpn"
    assert job.source_id == "3026362c-d2fa-44e6-a44a-64ff2d559779"  # ATS id, not site id 1989
    assert job.location == "Rotterdam, Nederland"
    assert job.url == "https://jobs.kpn.com/vacature/1989/ai-engineer-4"
    assert job.category == "Engineering"
    assert job.first_published == datetime(2026, 9, 7, 12, 0, 2,
                                           tzinfo=timezone(timedelta(hours=2)))


def test_description_is_plain_dutch_text(kpn_jobs):
    for job in kpn_jobs:
        assert job.description and "<" not in job.description
    medior = next(j for j in kpn_jobs if j.title.startswith("Medior"))
    assert "Minimaal 5 jaar ervaring" in medior.description
    assert medior.location == "Amersfoort, Nederland"


def test_rss_item_missing_from_api_is_skipped(kpn_jobs, capsys):
    assert sorted(j.title for j in kpn_jobs) == [
        "AI Engineer", "Medior Platform Engineer OpenShift", "Meewerkstage Design"]
    KpnAdapter(KPN).parse(_payload())
    assert "1 RSS items not in the API" in capsys.readouterr().err


def test_category_none_when_not_configured():
    company = CompanyConfig(name="kpn", source="kpn", base_url="https://jobs.kpn.com")
    assert all(j.category is None for j in KpnAdapter(company).parse(_payload()))


def test_config_requires_base_url():
    with pytest.raises(ValueError, match="^kpn: source 'kpn' requires base_url"):
        CompanyConfig(name="kpn", source="kpn")
