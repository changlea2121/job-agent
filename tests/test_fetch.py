from dataclasses import replace

import pytest

from job_agent import sources
from job_agent.__main__ import main
from job_agent.storage import JobStore

CONFIG = """\
companies:
  - name: adyen
    source: greenhouse
    board_token: adyen
    category_from: departments
    exclude_categories: [Enterprise Risk]
location_filter:
  match: [amsterdam]
"""


@pytest.fixture
def run_fetch(tmp_path, monkeypatch, capsys):
    """Run `fetch` with the greenhouse adapter replaced by one returning `jobs`."""
    config = tmp_path / "companies.yaml"
    config.write_text(CONFIG)
    db = tmp_path / "jobs.db"

    def run(jobs):
        class Fake:
            source = "greenhouse"

            def __init__(self, company, timeout):
                pass

            def fetch(self, known_ids):
                return jobs

        monkeypatch.setitem(sources.ADAPTERS, "greenhouse", Fake)
        code = main(["fetch", "--config", str(config), "--db", str(db)])
        return code, capsys.readouterr().out.splitlines()

    return run, db


def _with_categories(jobs, *categories):
    return [replace(j, category=c) for j, c in zip(jobs, categories)]


def test_reports_categories_not_stored_before(run_fetch, adyen_jobs):
    run, db = run_fetch
    a, b, c = adyen_jobs  # real adyen postings; categories set per test
    run(_with_categories([a], "Engineering"))
    code, out = run(_with_categories([a, b, c], "Engineering", "Data", "data"))
    assert code == 0
    # "data" matches "Data" case-insensitively, like exclude_categories.
    assert out == ["adyen: 3 fetched, 2 new", "adyen: new category: Data (2 jobs)",
                   "total: 3 fetched, 2 new"]


def test_new_category_already_excluded_is_marked(run_fetch, adyen_jobs):
    run, _ = run_fetch
    a, b, _ = adyen_jobs
    run(_with_categories([a], "Engineering"))
    _, out = run(_with_categories([a, b], "Engineering", "Enterprise Risk"))
    assert "adyen: new category: Enterprise Risk (1 job, excluded)" in out


def test_stored_category_and_no_category_are_not_reported(run_fetch, adyen_jobs):
    run, _ = run_fetch
    a, b, c = adyen_jobs
    run(_with_categories([a], "Engineering"))
    _, out = run(_with_categories([a, b, c], "Engineering", "Engineering", None))
    assert not any("new category" in line for line in out)


def test_first_fetch_reports_every_category(run_fetch, adyen_jobs):
    run, _ = run_fetch
    _, out = run(adyen_jobs)  # all three are "Account Management"
    assert "adyen: new category: Account Management (3 jobs)" in out


def test_categories_per_source_and_company(tmp_path, adyen_jobs, nebius_jobs):
    store = JobStore(tmp_path / "jobs.db")
    store.insert_new(adyen_jobs + nebius_jobs)
    assert store.categories("greenhouse", "adyen") == {"Account Management"}
    assert store.categories("workday", "adyen") == set()
    assert None not in store.categories("greenhouse", "nebius")
