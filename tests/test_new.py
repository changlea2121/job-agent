from dataclasses import replace
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
    # Drop the leading job-ref column (tested separately); keep "# ..." headers.
    rows = [line.split("\t") for line in lines[:-1]]
    return code, [r if r[0].startswith("#") else r[1:] for r in rows], lines[-1]


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
        "3 new jobs, 0 internships (2 location unclear) "
        "since 2026-10-05T09:00:00.000000+00:00; "
        "5 new before filters, 2 excluded (location 2, category 0, seniority 0, title 0, experience 0)"
    )


def test_rows_start_with_job_ref(capsys, setup):
    main(["new", *setup])
    first = capsys.readouterr().out.splitlines()[0].split("\t")
    assert first[:2] == ["nebius:4981489101", "nebius"]


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


FULL_CONFIG = """\
companies:
  - {name: adyen, source: greenhouse, board_token: adyen,
     category_from: departments, exclude_categories: [account management]}
  - {name: nebius, source: greenhouse, board_token: nebius,
     category_metadata_field: Job Category,
     exclude_categories: [Hardware Infrastructure]}
location_filter:
  match: [amsterdam, rotterdam]
  unclear: [netherlands]
title_filter:
  exclude_seniority: [senior, head of]
  internship: [intern]
"""


@pytest.fixture
def full_setup(tmp_path, adyen_jobs, nebius_location_jobs):
    """All fixture jobs in one run, with category and seniority rules.

    Adds one synthetic internship, derived from a real Amsterdam posting,
    since neither board currently lists an internship.
    """
    intern = replace(nebius_location_jobs[0], source_id="intern-1",
                     title="Data Engineering Intern")
    config = tmp_path / "companies.yaml"
    config.write_text(FULL_CONFIG)
    db = tmp_path / "jobs.db"
    store = JobStore(db)
    store.record_run(now=T1)
    store.insert_new([*adyen_jobs, *nebius_location_jobs, intern], now=T1)
    store.close()
    return ["--config", str(config), "--db", str(db)]


def test_rules_and_internship_section(capsys, full_setup):
    code, rows, summary = run_new(capsys, full_setup)
    assert code == 0
    assert [r[:2] for r in rows] == [
        ["nebius", "AI Science Writer, Nebius Academy (Contract)"],
        ["# internships"],
        ["nebius", "Data Engineering Intern"],
    ]
    assert summary == (
        "1 new jobs, 1 internships (0 location unclear) "
        "since 2026-10-01T09:00:00.000000+00:00; "
        "9 new before filters, 7 excluded (location 4, category 2, seniority 1, title 0, experience 0)"
    )


def test_show_excluded_lists_first_rule_per_job(capsys, full_setup):
    _, rows, summary = run_new(capsys, [*full_setup, "--show-excluded"])
    excluded = rows[rows.index(["# excluded"]) + 1:]
    # Excluded rows carry the reason as a sixth column and no unclear tag.
    assert sorted((r[0], r[1], r[2], r[5]) for r in excluded) == sorted([
        ("adyen", "Account Manager", "Paris", "location: Paris"),
        ("adyen", "Account Manager", "Shanghai", "location: Shanghai"),
        ("adyen", "Account Manager", "Amsterdam", "category: Account Management"),
        # Location is checked first: "Head of" in London counts as location.
        ("nebius", "Head of Employee Relations",
         "London, United Kingdom; Remote - Europe",
         "location: London, United Kingdom; Remote - Europe"),
        ("nebius", "Application Integration Developer", "Remote - Europe",
         "location: Remote - Europe"),
        ("nebius", "Technical Program Manager - New Data Center Launches",
         "Netherlands; Remote - Europe", "category: Hardware Infrastructure"),
        ("nebius", "Senior Data Engineer",
         "Germany; Israel; Netherlands; Prague, Czech Republic; "
         "Remote - Europe; United Kingdom", "seniority: senior"),
    ])
    assert summary.endswith("(location 4, category 2, seniority 1, title 0, experience 0)")


def test_excluded_hidden_by_default(capsys, full_setup):
    _, rows, _ = run_new(capsys, full_setup)
    assert ["# excluded"] not in rows


def test_title_rule_counts_and_applies_to_internships(capsys, tmp_path, nebius_location_jobs):
    analyst = replace(nebius_location_jobs[0], source_id="ba-1",
                      title="Business Analyst")
    intern = replace(nebius_location_jobs[0], source_id="ba-2",
                     title="Business Analyst Intern")
    config = tmp_path / "companies.yaml"
    config.write_text(FULL_CONFIG + "  exclude_titles: [business analyst]\n")
    db = tmp_path / "jobs.db"
    store = JobStore(db)
    store.record_run(now=T1)
    store.insert_new([nebius_location_jobs[0], analyst, intern], now=T1)
    store.close()
    _, rows, summary = run_new(
        capsys, ["--config", str(config), "--db", str(db), "--show-excluded"])
    excluded = rows[rows.index(["# excluded"]) + 1:]
    assert sorted((r[1], r[5]) for r in excluded) == [
        ("Business Analyst", "title: business analyst"),
        ("Business Analyst Intern", "title: business analyst"),
    ]
    assert ["# internships"] not in rows
    assert summary.endswith("(location 0, category 0, seniority 0, title 2, experience 0)")
