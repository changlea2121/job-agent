from datetime import datetime, timezone

import pytest

from job_agent.__main__ import main
from job_agent.storage import JobStore

CONFIG = """\
companies: []
location_filter:
  match: [amsterdam, rotterdam]
  unclear: [netherlands]
"""

T1 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path, adyen_jobs, nebius_location_jobs):
    """Run 1 (T1) stores the adyen fixture; run 2 (T2) the nebius location fixture."""
    config = tmp_path / "companies.yaml"
    config.write_text(CONFIG)
    db = tmp_path / "jobs.db"
    store = JobStore(db)
    store.record_run(now=T1)
    store.insert_new(adyen_jobs, now=T1)
    store.record_run(now=T2)
    store.insert_new(nebius_location_jobs, now=T2)
    store.close()
    return ["--config", str(config), "--db", str(db)]


def run_new(capsys, args):
    code = main(["new", *args])
    lines = capsys.readouterr().out.splitlines()
    return code, [line.split("\t") for line in lines[:-1]], lines[-1]


def test_new_lists_latest_run_with_unclear_marked(capsys, setup):
    code, rows, summary = run_new(capsys, setup)
    assert code == 0
    assert [(r[0], r[2]) for r in rows] == [
        ("nebius", "Amsterdam, Netherlands; Remote - Europe"),
        ("nebius", "Germany; Israel; Netherlands; Prague, Czech Republic; "
                   "Remote - Europe; United Kingdom [location unclear]"),
        ("nebius", "Netherlands; Remote - Europe [location unclear]"),
    ]
    assert rows[0] == [
        "nebius", "AI Science Writer, Nebius Academy (Contract)",
        "Amsterdam, Netherlands; Remote - Europe", "Academy and Science",
        "https://careers.nebius.com/?gh_jid=4981489101",
    ]
    assert summary == (
        "3 new jobs (2 location unclear) since 2026-10-05T09:00:00.000000+00:00; "
        "5 new before location filter"
    )


def test_since_includes_earlier_runs(capsys, setup):
    code, rows, summary = run_new(capsys, [*setup, "--since", "2026-10-01"])
    assert code == 0
    assert [(r[0], r[2]) for r in rows if r[0] == "adyen"] == [
        ("adyen", "Amsterdam"),  # the only adyen fixture job in a matched city
    ]
    assert len(rows) == 4
    assert "since 2026-10-01T00:00:00.000000+00:00" in summary


def test_since_with_offset_is_converted_to_utc(capsys, setup):
    # 11:00+02:00 == 09:00 UTC == T2: only the second run's jobs.
    _, rows, _ = run_new(capsys, [*setup, "--since", "2026-10-05T11:00+02:00"])
    assert {r[0] for r in rows} == {"nebius"}


def test_since_after_all_runs_lists_nothing(capsys, setup):
    _, rows, summary = run_new(capsys, [*setup, "--since", "2026-10-06"])
    assert rows == []
    assert summary.startswith("0 new jobs")


def test_since_rejects_non_iso(capsys, setup):
    with pytest.raises(SystemExit):
        main(["new", *setup, "--since", "last tuesday"])
    assert "not an ISO date" in capsys.readouterr().err


def test_new_without_runs_fails(capsys, tmp_path):
    config = tmp_path / "companies.yaml"
    config.write_text(CONFIG)
    assert main(["new", "--config", str(config), "--db", str(tmp_path / "x.db")]) == 1
    assert "no fetch runs" in capsys.readouterr().err
