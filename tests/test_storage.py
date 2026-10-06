from datetime import datetime

from job_agent.storage import JobStore


def test_first_run_inserts_all(tmp_path, nebius_jobs):
    store = JobStore(tmp_path / "jobs.db")
    assert store.insert_new(nebius_jobs) == len(nebius_jobs) == 3
    assert store.count() == 3


def test_second_run_of_same_fixture_reports_zero_new(tmp_path, nebius_jobs):
    store = JobStore(tmp_path / "jobs.db")
    assert store.insert_new(nebius_jobs) == 3
    assert store.insert_new(nebius_jobs) == 0
    assert store.count() == 3


def test_partial_overlap_counts_only_unseen(tmp_path, nebius_jobs):
    store = JobStore(tmp_path / "jobs.db")
    assert store.insert_new(nebius_jobs[:1]) == 1
    assert store.insert_new(nebius_jobs) == 2


def test_key_includes_company(tmp_path, adyen_jobs, nebius_jobs):
    store = JobStore(tmp_path / "jobs.db")
    assert store.insert_new(adyen_jobs) == 3
    assert store.insert_new(nebius_jobs) == 3
    assert store.count() == 6


def test_first_seen_at_is_utc_and_not_overwritten(tmp_path, nebius_jobs):
    store = JobStore(tmp_path / "jobs.db")
    store.insert_new(nebius_jobs)
    query = "SELECT first_seen_at, first_published FROM jobs WHERE source_id = ?"
    seen1, published = store.conn.execute(query, ("4959063101",)).fetchone()
    store.insert_new(nebius_jobs)
    seen2, _ = store.conn.execute(query, ("4959063101",)).fetchone()

    assert seen1 == seen2
    assert datetime.fromisoformat(seen1).utcoffset().total_seconds() == 0
    assert published == "2026-08-25T08:02:07-04:00"
