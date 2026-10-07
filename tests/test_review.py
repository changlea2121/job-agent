import io
import json

import pytest

from job_agent.__main__ import main
from job_agent.matching import keyword_pattern
from job_agent.review import preview
from job_agent.storage import JobStore

from test_labels import CONFIG

T1 = "2026-10-01T09:00:00+00:00"

# With CONFIG, in review order:
#   kept:     WRITER (Amsterdam), TPM (Netherlands -> unclear)
#   excluded: ADYEN_AMS (category), SENIOR (seniority), then 4 by location
WRITER, TPM = "4981489101", "4817126101"
ADYEN_AMS, SENIOR = "7436701", "4724503101"


@pytest.fixture
def setup(tmp_path, adyen_jobs, nebius_location_jobs):
    config = tmp_path / "companies.yaml"
    config.write_text(CONFIG)
    db = tmp_path / "jobs.db"
    store = JobStore(db)
    store.insert_new([*adyen_jobs, *nebius_location_jobs])
    store.close()
    labels = tmp_path / "labels.jsonl"
    return ["--config", str(config), "--db", str(db), "--labels", str(labels)], labels


def run_review(capsys, monkeypatch, args, keys):
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(k + "\n" for k in keys)))
    code = main(["review", *args])
    return code, capsys.readouterr().out


def summary(out):
    """The last line, minus a prompt left on it (piped input echoes no newline)."""
    return out.splitlines()[-1].rsplit("> ", 1)[-1]


def labels_by_id(path):
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text().splitlines())
    return {r["source_id"]: r for r in rows}


def test_review_labels_kept_jobs_in_order(capsys, monkeypatch, setup):
    args, labels = setup
    code, out = run_review(capsys, monkeypatch, args, ["y", "n", "2"])
    assert code == 0
    assert "[1/2] nebius:4981489101" in out
    assert "[2/2] nebius:4817126101" in out
    assert "location: Netherlands; Remote - Europe [location unclear]" in out
    assert "excluded by" not in out
    # Reasons are listed with their descriptions.
    assert "  2 too_senior      senior-level scope" in out
    assert summary(out) == (
        f"2 labelled, 0 skipped, 0 left unlabelled; 2 labels in {labels}")
    got = labels_by_id(labels)
    assert got[WRITER]["label"] == "yes"
    assert (got[TPM]["label"], got[TPM]["reasons"]) == ("no", ["too_senior"])
    assert got[TPM]["filter"]["decision"] == "kept"


def test_skip_quit_and_resume(capsys, monkeypatch, setup):
    args, labels = setup
    _, out = run_review(capsys, monkeypatch, args, ["s", "m", "", "q"])
    assert summary(out).startswith("1 labelled, 1 skipped, 1 left unlabelled")
    assert labels_by_id(labels)[TPM]["label"] == "maybe"
    # Next session: the skipped job comes back, the labelled one does not.
    _, out = run_review(capsys, monkeypatch, args, ["q"])
    assert "[1/1] nebius:4981489101" in out
    assert "nebius:4817126101" not in out


def test_eof_quits_after_saving_previous_labels(capsys, monkeypatch, setup):
    args, labels = setup
    code, out = run_review(capsys, monkeypatch, args, ["y"])  # then EOF
    assert code == 0
    assert set(labels_by_id(labels)) == {WRITER}
    assert "1 labelled, 0 skipped, 1 left unlabelled" in out


def test_invalid_input_asks_again(capsys, monkeypatch, setup):
    args, labels = setup
    keys = ["x", "n", "", "9", "1 3", "", "  only in 2027 ", "q"]
    _, out = run_review(capsys, monkeypatch, args, keys)
    assert "unknown key" in out
    assert "a 'no' label needs at least one reason" in out
    assert "enter numbers from 1 to 3" in out
    assert "a note is required" in out
    got = labels_by_id(labels)[WRITER]
    assert (got["reasons"], got["note"]) == (["dutch_required", "other"], "only in 2027")


def test_d_shows_full_description(capsys, monkeypatch, setup, nebius_location_jobs):
    args, _ = setup
    description = nebius_location_jobs[0].description
    _, out = run_review(capsys, monkeypatch, args, ["d", "q"])
    before_d, after_d = out.split("(d: full description)", 1)
    assert description not in before_d
    assert description in after_d


def test_review_preview_shows_keyword_lines(capsys, monkeypatch, setup):
    args, _ = setup
    _, out = run_review(capsys, monkeypatch, args, ["q"])
    head = out.split("[y]es")[0]  # the first job's card
    assert "matching lines:\n  You may be an AI/ML researcher" in head
    assert "\n  - Have professional or academic experience in AI/ML" in head


def test_preview_cuts_at_word():
    assert preview("short") == "short"
    assert preview("alpha beta gamma", limit=12) == "alpha beta …\n(d: full description)"


KEYWORDS = keyword_pattern(("years", "dutch"))
INTRO = "About us. " * 30  # 300 characters of company intro


def test_preview_lists_matching_lines_then_start():
    text = "About us.\n- 3+ Years of Python\n- Fluent DUTCH is a plus\n- Yearly bonus"
    assert preview(text, KEYWORDS) == "\n".join([
        "matching lines:",
        "  - 3+ Years of Python",  # case-insensitive
        "  - Fluent DUTCH is a plus",  # "Yearly" is not the whole word "years"
        "",
        text,  # it all fits, so no "(d: full description)"
    ])


def test_preview_cuts_start_to_remaining_room():
    text = f"- 5 years of Go\n{INTRO}"
    out = preview(text, KEYWORDS, limit=200)
    start = out.split("\n\n", 1)[1]
    assert start.startswith("- 5 years of Go\nAbout us.")
    assert len(start.splitlines()[1]) <= 200 - len("- 5 years of Go")
    assert out.endswith(" …\n(d: full description)")


def test_preview_skips_start_when_little_room():
    text = f"{INTRO}\n" + "\n".join(f"- {n} years of X" for n in range(1, 30))
    out = preview(text, KEYWORDS, limit=200)
    assert "About us" not in out
    assert "  - 1 years of X" in out
    assert "more)" in out  # not all matching lines fit
    assert out.endswith("(d: full description)")


def test_preview_cuts_long_matching_lines():
    long_line = "Dutch " + "word " * 100
    out = preview(long_line, KEYWORDS)
    first = out.splitlines()[1]
    assert first.endswith(" …") and len(first) <= 2 + 200 + 2


def test_preview_without_matches_is_start_only():
    out = preview(INTRO, KEYWORDS, limit=100)
    assert out.startswith("About us.") and "matching lines" not in out


def test_since_limits_jobs(capsys, monkeypatch, setup):
    args, _ = setup
    code, out = run_review(capsys, monkeypatch, [*args, "--since", "2999-01-01"], [])
    assert (code, out.strip()) == (0, "nothing to review")


def test_excluded_reviews_removed_jobs(capsys, monkeypatch, setup):
    args, labels = setup
    code, out = run_review(capsys, monkeypatch, [*args, "--excluded"],
                           ["y", "n", "2", "q"])
    assert code == 0
    # Category and seniority exclusions come before the 4 location ones.
    assert "[1/6] adyen:7436701" in out
    assert "excluded by: category: Account Management" in out
    assert "[2/6] nebius:4724503101" in out
    assert "excluded by: seniority: senior" in out
    assert summary(out).endswith("; 1 excluded jobs labelled yes/maybe")
    got = labels_by_id(labels)
    assert got[ADYEN_AMS]["filter"] == {
        "decision": "excluded", "rule": "category", "detail": "Account Management"}
    assert got[SENIOR]["filter"]["rule"] == "seniority"
    # Labelled excluded jobs no longer come up, and kept jobs never did.
    _, out = run_review(capsys, monkeypatch, [*args, "--excluded"], ["q"])
    assert "[1/4]" in out
    assert "excluded by: location" in out


def test_rule_narrows_excluded(capsys, monkeypatch, setup):
    args, _ = setup
    _, out = run_review(capsys, monkeypatch,
                        [*args, "--excluded", "--rule", "seniority"], ["q"])
    assert "[1/1] nebius:4724503101" in out
    _, out = run_review(capsys, monkeypatch,
                        [*args, "--excluded", "--rule", "location", "--rule", "category"],
                        ["q"])
    assert "[1/5] adyen:7436701" in out


def test_rule_requires_excluded(capsys, setup):
    args, _ = setup
    assert main(["review", *args, "--rule", "location"]) == 1
    assert "--rule only applies with --excluded" in capsys.readouterr().err
