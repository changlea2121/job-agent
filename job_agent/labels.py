"""Relevance labels for building an evaluation set.

Labels live in a JSON Lines file separate from jobs.db, one object per job,
keyed by (source, company, source_id). Each label carries a snapshot of the
job and the filter decision at labelling time, so the file stays usable after
postings close or jobs.db is rebuilt.
"""
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .filtering import apply_filters
from .models import Job
from .storage import utc_iso

LABELS = ("yes", "maybe", "no")
NOTE_REASON = "other"  # the reason that needs a note

Key = tuple[str, str, str]  # (source, company, source_id)


def job_ref(job: Job) -> str:
    """Short reference shown by `new` and accepted by `label`."""
    return f"{job.company}:{job.source_id}"


def parse_ref(ref: str) -> tuple[str | None, str, str]:
    """`company:source_id` or `source:company:source_id` -> (source, company, source_id)."""
    parts = ref.split(":")
    if len(parts) == 2 and all(parts):
        return None, parts[0], parts[1]
    if len(parts) == 3 and all(parts):
        return parts[0], parts[1], parts[2]
    raise ValueError(f"bad job ref {ref!r}; expected company:id or source:company:id")


@dataclass(frozen=True)
class FilterDecision:
    decision: str  # "kept" or "excluded"
    rule: str | None = None  # for "excluded": the first rule that removed the job
    detail: str | None = None

    def __post_init__(self):
        if self.decision not in ("kept", "excluded"):
            raise ValueError(f"filter decision must be 'kept' or 'excluded', got {self.decision!r}")


def filter_decision(job: Job, config: Config) -> FilterDecision:
    result = apply_filters([job], config)
    if result.excluded:
        _, rule, detail = result.excluded[0]
        return FilterDecision("excluded", rule, detail)
    return FilterDecision("kept")


@dataclass(frozen=True)
class Snapshot:
    """The job as it was when labelled."""
    title: str
    location: str
    category: str | None
    url: str
    description: str

    @classmethod
    def from_job(cls, job: Job) -> "Snapshot":
        return cls(job.title, job.location, job.category, job.url, job.description)


@dataclass(frozen=True)
class Label:
    source: str
    company: str
    source_id: str
    label: str
    reasons: tuple[str, ...]
    note: str | None
    labelled_at: str  # ISO 8601 UTC
    filter: FilterDecision
    job: Snapshot

    @property
    def key(self) -> Key:
        return (self.source, self.company, self.source_id)

    @property
    def ref(self) -> str:
        return f"{self.company}:{self.source_id}"

    def to_job(self) -> Job:
        """Rebuild a Job from the snapshot (without first_published)."""
        s = self.job
        return Job(self.source, self.company, self.source_id, s.title, s.location,
                   s.url, s.description, s.category, first_published=None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Label":
        try:
            return cls(
                source=d["source"], company=d["company"], source_id=d["source_id"],
                label=d["label"], reasons=tuple(d["reasons"]), note=d.get("note"),
                labelled_at=d["labelled_at"], filter=FilterDecision(**d["filter"]),
                job=Snapshot(**d["job"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed label: {exc}") from None


def validate(label: str, reasons: Iterable[str], note: str | None,
             allowed: Iterable[str]) -> None:
    """Raise ValueError unless the label, reasons and note fit together."""
    reasons, allowed = list(reasons), list(allowed)
    if label not in LABELS:
        raise ValueError(f"label must be one of {', '.join(LABELS)}, got {label!r}")
    unknown = [r for r in reasons if r not in allowed]
    if unknown:
        raise ValueError(f"unknown reason(s) {', '.join(unknown)}; "
                         f"allowed: {', '.join(allowed)}")
    if len(set(reasons)) != len(reasons):
        raise ValueError("reasons must not repeat")
    if label == "yes" and reasons:
        raise ValueError("a 'yes' label takes no reasons")
    if label == "no" and not reasons:
        raise ValueError("a 'no' label needs at least one reason")
    if NOTE_REASON in reasons and not note:
        raise ValueError(f"reason {NOTE_REASON!r} needs a note")
    if note and NOTE_REASON not in reasons:
        raise ValueError(f"a note is only stored with reason {NOTE_REASON!r}")


def make_label(job: Job, label: str, reasons: Iterable[str], note: str | None,
               config: Config, now: datetime | None = None) -> Label:
    """Validate and build a label, snapshotting the job and the current filter decision."""
    reasons = tuple(reasons)
    note = note.strip() if note and note.strip() else None
    validate(label, reasons, note, config.label_reasons)
    return Label(
        source=job.source, company=job.company, source_id=job.source_id,
        label=label, reasons=reasons, note=note, labelled_at=utc_iso(now),
        filter=filter_decision(job, config), job=Snapshot.from_job(job),
    )


class LabelStore:
    """All labels in one JSON Lines file; every change rewrites it atomically."""

    def __init__(self, path: str | Path, allowed_reasons: Iterable[str]):
        self.path = Path(path)
        self.labels: dict[Key, Label] = {}
        if self.path.exists():
            self._load(list(allowed_reasons))

    def _load(self, allowed: list[str]) -> None:
        with open(self.path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    label = Label.from_dict(json.loads(line))
                    validate(label.label, label.reasons, label.note, allowed)
                except ValueError as exc:  # includes json.JSONDecodeError
                    raise ValueError(f"{self.path}:{n}: {exc}") from None
                if label.key in self.labels:
                    raise ValueError(f"{self.path}:{n}: duplicate label for {label.ref}")
                self.labels[label.key] = label

    def __contains__(self, key: Key) -> bool:
        return key in self.labels

    def __len__(self) -> int:
        return len(self.labels)

    def find(self, company: str, source_id: str, source: str | None = None) -> list[Label]:
        return [l for l in self.labels.values()
                if l.company == company and l.source_id == source_id
                and source in (None, l.source)]

    def set(self, label: Label) -> None:
        """Add or replace the label for this job and save."""
        self.labels[label.key] = label
        self.save()

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for key in sorted(self.labels):
                f.write(json.dumps(self.labels[key].to_dict(), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
