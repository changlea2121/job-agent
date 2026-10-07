import json
from dataclasses import replace

import pytest

from job_agent.__main__ import main
from job_agent.config import load_config
from job_agent.labels import LabelStore, make_label, parse_ref, validate
from job_agent.storage import JobStore

REASONS = ("dutch_required", "too_senior", "other")

# Kept: AI Science Writer (Amsterdam), TPM (Netherlands, unclear).
# Excluded: adyen Amsterdam (category), Senior Data Engineer (seniority),
# the rest by location.
CONFIG = """\
companies:
  - {name: adyen, source: greenhouse, board_token: adyen,
     category_from: departments, exclude_categories: [account management]}
location_filter:
  match: [amsterdam]
  unclear: [netherlands]
title_filter:
  exclude_seniority: [senior, head of]
label_reasons:
  dutch_required: Dutch is mandatory
  too_senior: senior-level scope
  other: anything else
preview_keywords: [experience]
"""

WRITER = "nebius:4981489101"  # kept
SENIOR = "nebius:4724503101"  # excluded by seniority


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


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- config ---------------------------------------------------------------

def test_label_reasons_loaded_in_order(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(CONFIG)
    assert list(load_config(path).label_reasons) == list(REASONS)
    assert load_config(path).label_reasons["too_senior"] == "senior-level scope"


@pytest.mark.parametrize("section, message", [
    ("label_reasons: [a, b]", "mapping"),
    ("label_reasons: {}", "mapping"),
    ("label_reasons: {Too-Senior: x}", "invalid name"),
    ("label_reasons: {too_senior: ''}", "non-empty"),
    ("label_reasons: {too_senior: 3}", "non-empty"),
])
def test_bad_label_reasons_fail_at_load(tmp_path, section, message):
    path = tmp_path / "c.yaml"
    path.write_text(f"companies: []\n{section}\n")
    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_preview_keywords(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(CONFIG)
    assert load_config(path).preview_keywords == ("experience",)
    path.write_text("companies: []\npreview_keywords: experience\n")
    with pytest.raises(ValueError, match="preview_keywords must be a list"):
        load_config(path)


def test_label_reasons_optional(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("companies: []\n")
    assert load_config(path).label_reasons == {}


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("label, reasons, note", [
    ("yes", [], None),
    ("maybe", [], None),
    ("maybe", ["too_senior"], None),
    ("no", ["too_senior", "dutch_required"], None),
    ("no", ["other"], "starts in 2027"),
])
def test_valid_labels(label, reasons, note):
    validate(label, reasons, note, REASONS)


@pytest.mark.parametrize("label, reasons, note, message", [
    ("nope", [], None, "label must be"),
    ("yes", ["too_senior"], None, "takes no reasons"),
    ("no", [], None, "at least one reason"),
    ("no", ["start_date"], None, "unknown reason"),
    ("no", ["too_senior", "too_senior"], None, "repeat"),
    ("no", ["other"], None, "needs a note"),
    ("maybe", ["too_senior"], "why", "only stored with reason 'other'"),
])
def test_invalid_labels(label, reasons, note, message):
    with pytest.raises(ValueError, match=message):
        validate(label, reasons, note, REASONS)


@pytest.mark.parametrize("ref, parsed", [
    ("nebius:42", (None, "nebius", "42")),
    ("greenhouse:nebius:42", ("greenhouse", "nebius", "42")),
])
def test_parse_ref(ref, parsed):
    assert parse_ref(ref) == parsed


@pytest.mark.parametrize("ref", ["nebius", "nebius:", ":42", "a:b:c:d"])
def test_parse_ref_rejects(ref):
    with pytest.raises(ValueError, match="bad job ref"):
        parse_ref(ref)


# --- store ------------------------------------------------------------------

def test_store_round_trip_sorted_and_replacing(tmp_path, nebius_location_jobs):
    config = load_config(_write(tmp_path, CONFIG))
    path = tmp_path / "labels.jsonl"
    store = LabelStore(path, REASONS)
    writer, senior = nebius_location_jobs[0], nebius_location_jobs[1]
    store.set(make_label(writer, "yes", [], None, config))
    store.set(make_label(senior, "maybe", ["too_senior"], None, config))
    store.set(make_label(writer, "no", ["other"], "  contract role ", config))

    rows = read_lines(path)
    assert [r["source_id"] for r in rows] == sorted([writer.source_id, senior.source_id])
    loaded = LabelStore(path, REASONS)
    assert len(loaded) == 2
    relabelled = loaded.labels[("greenhouse", "nebius", writer.source_id)]
    assert (relabelled.label, relabelled.reasons, relabelled.note) == (
        "no", ("other",), "contract role")
    assert relabelled.job.description == writer.description
    assert not (tmp_path / "labels.jsonl.tmp").exists()


@pytest.mark.parametrize("line, message", [
    ("not json", r"labels.jsonl:2: "),
    ('{"source": "greenhouse"}', "labels.jsonl:2: malformed label"),
])
def test_store_rejects_bad_lines(tmp_path, nebius_location_jobs, line, message):
    path = _labelled_file(tmp_path, nebius_location_jobs[0])
    path.write_text(path.read_text() + line + "\n")
    with pytest.raises(ValueError, match=message):
        LabelStore(path, REASONS)


def test_store_rejects_reason_no_longer_configured(tmp_path, nebius_location_jobs):
    path = _labelled_file(tmp_path, nebius_location_jobs[0])
    with pytest.raises(ValueError, match="labels.jsonl:1: unknown reason"):
        LabelStore(path, ("dutch_required", "other"))


def _write(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text)
    return path


def _labelled_file(tmp_path, job):
    path = tmp_path / "labels.jsonl"
    store = LabelStore(path, REASONS)
    store.set(make_label(job, "no", ["too_senior"], None, load_config(_write(tmp_path, CONFIG))))
    return path


# --- label command ----------------------------------------------------------

def test_label_command_stores_snapshot_and_filter_decision(
        capsys, setup, nebius_location_jobs):
    args, labels = setup
    assert main(["label", WRITER, "yes", *args]) == 0
    assert main(["label", SENIOR, "no", "--reason", "too_senior",
                 "--reason", "dutch_required", *args]) == 0
    assert "nebius:4724503101: no (too_senior, dutch_required) [excluded]" in (
        capsys.readouterr().out)

    senior, writer = read_lines(labels)  # sorted by key: 4724503101 < 4981489101
    assert writer["filter"] == {"decision": "kept", "rule": None, "detail": None}
    assert writer["job"] == {
        "title": "AI Science Writer, Nebius Academy (Contract)",
        "location": "Amsterdam, Netherlands; Remote - Europe",
        "category": "Academy and Science",
        "url": "https://careers.nebius.com/?gh_jid=4981489101",
        "description": nebius_location_jobs[0].description,  # full, not a preview
    }
    assert writer["note"] is None
    assert senior["filter"] == {"decision": "excluded", "rule": "seniority",
                                "detail": "senior"}
    assert senior["reasons"] == ["too_senior", "dutch_required"]


def test_label_command_requires_note_with_other(capsys, setup):
    args, labels = setup
    assert main(["label", WRITER, "no", "--reason", "other", *args]) == 1
    assert "needs a note" in capsys.readouterr().err
    assert not labels.exists()
    assert main(["label", WRITER, "no", "--reason", "other",
                 "--note", "contract only", *args]) == 0
    assert read_lines(labels)[0]["note"] == "contract only"


def test_label_command_validation_errors(capsys, setup):
    args, labels = setup
    assert main(["label", WRITER, "no", *args]) == 1
    assert main(["label", WRITER, "no", "--reason", "start_date", *args]) == 1
    assert main(["label", "nebius:999", "yes", *args]) == 1
    assert main(["label", "nebius", "yes", *args]) == 1
    err = capsys.readouterr().err
    assert "at least one reason" in err
    assert "unknown reason" in err
    assert "no job 'nebius:999'" in err
    assert "bad job ref" in err
    assert not labels.exists()


def test_label_command_ambiguous_ref(capsys, setup, nebius_location_jobs):
    args, _ = setup
    db = args[args.index("--db") + 1]
    store = JobStore(db)
    store.insert_new([replace(nebius_location_jobs[0], source="lever")])
    store.close()
    assert main(["label", WRITER, "yes", *args]) == 1
    assert "ambiguous" in capsys.readouterr().err
    assert main(["label", f"lever:{WRITER}", "yes", *args]) == 0


def test_relabel_after_db_rebuild_uses_snapshot(capsys, setup, tmp_path):
    args, labels = setup
    assert main(["label", WRITER, "yes", *args]) == 0
    before = read_lines(labels)[0]

    # Rebuild: a fresh, empty jobs.db. The labels file is untouched.
    args[args.index("--db") + 1] = str(tmp_path / "rebuilt.db")
    assert read_lines(labels) == [before]
    assert main(["label", WRITER, "maybe", "--reason", "dutch_required", *args]) == 0
    (after,) = read_lines(labels)
    assert after["label"] == "maybe"
    assert after["job"] == before["job"]
    assert after["filter"] == before["filter"]


def test_label_command_needs_label_reasons(capsys, setup, tmp_path):
    args, _ = setup
    args[args.index("--config") + 1] = str(_write(tmp_path, "companies: []\n"))
    assert main(["label", WRITER, "yes", *args]) == 1
    assert "no label_reasons" in capsys.readouterr().err


def test_separate_label_files(capsys, setup, tmp_path):
    args, alice = setup
    bob = tmp_path / "labels-bob.jsonl"
    assert main(["label", WRITER, "yes", *args]) == 0
    args[args.index("--labels") + 1] = str(bob)
    assert main(["label", WRITER, "no", "--reason", "too_senior", *args]) == 0
    assert read_lines(alice)[0]["label"] == "yes"
    assert read_lines(bob)[0]["label"] == "no"
