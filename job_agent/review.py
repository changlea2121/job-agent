"""Interactive labelling: step through jobs one at a time."""
import re
from collections.abc import Callable
from dataclasses import dataclass

from .config import Config
from .filtering import RULES, apply_filters
from .labels import NOTE_REASON, LabelStore, job_ref, make_label
from .matching import keyword_pattern, normalize
from .models import Job

PREVIEW_CHARS = 1000
LINE_CHARS = 200  # matching lines are cut to this; long ones are mostly boilerplate
MIN_START_CHARS = 150  # less room than this: skip the start of the description
# Rules that need a human look come first; most location exclusions are
# plainly elsewhere in the world.
EXCLUDED_ORDER = ("category", "seniority", "location")
assert sorted(EXCLUDED_ORDER) == sorted(RULES)

PROMPT = "[y]es [m]aybe [n]o [d]escription [s]kip [q]uit > "
_CHOICES = {"y": "yes", "m": "maybe", "n": "no"}


@dataclass(frozen=True)
class Candidate:
    job: Job
    unclear: bool = False  # location only "Netherlands"
    excluded_by: tuple[str, str] | None = None  # (rule, detail)


@dataclass
class ReviewStats:
    total: int
    labelled: int = 0
    skipped: int = 0
    # Excluded jobs labelled yes or maybe: the filters may be too strict.
    false_exclusions: int = 0

    @property
    def remaining(self) -> int:
        return self.total - self.labelled


def candidates(jobs: list[Job], config: Config, labels: LabelStore, *,
               excluded: bool = False, rules: list[str] | None = None) -> list[Candidate]:
    """Unlabelled jobs to review: kept ones (and internships) by default, or
    excluded ones, optionally only those removed by `rules`."""
    result = apply_filters(jobs, config)
    if excluded:
        found = [Candidate(job, excluded_by=(rule, detail))
                 for job, rule, detail in result.excluded
                 if rules is None or rule in rules]
        found.sort(key=lambda c: EXCLUDED_ORDER.index(c.excluded_by[0]))
    else:
        found = [Candidate(job, unclear=job in result.unclear)
                 for job in result.jobs + result.internships]
    return [c for c in found
            if (c.job.source, c.job.company, c.job.source_id) not in labels]


def _cut(text: str, limit: int) -> str:
    """`text`, or its first `limit` characters cut back to a word, plus " …"."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(None, 1)[0] + " …"


def preview(text: str, keywords: re.Pattern[str] | None = None,
            limit: int = PREVIEW_CHARS) -> str:
    """Lines matching `keywords` (normalized text), then the start of `text`
    if at least MIN_START_CHARS of the `limit` are left."""
    matching = [_cut(line, LINE_CHARS) for line in text.splitlines()
                if keywords is not None and keywords.search(normalize(line))]
    shown, used = [], 0
    for line in matching:
        if shown and used + len(line) > limit:
            break
        shown.append(line)
        used += len(line)
    out, truncated = [], len(shown) < len(matching)
    if shown:
        out += ["matching lines:", *(f"  {line}" for line in shown)]
        if truncated:
            out.append(f"  (+{len(matching) - len(shown)} more)")
    room = limit - used
    if not shown or room >= MIN_START_CHARS:
        start = _cut(text, room)
        truncated = truncated or start != text
        out += ["", start] if shown else [start]
    else:
        truncated = True
    if truncated:
        out.append("(d: full description)")
    return "\n".join(out)


class _Quit(Exception):
    pass


def review(cands: list[Candidate], labels: LabelStore, config: Config, *,
           input_fn: Callable[[str], str] = input,
           out: Callable[[str], None] = print) -> ReviewStats:
    """Label candidates interactively; each label is saved as soon as it is given."""
    stats = ReviewStats(total=len(cands))
    reasons = list(config.label_reasons)
    keywords = keyword_pattern(config.preview_keywords) if config.preview_keywords else None

    def ask(prompt: str) -> str:
        try:
            return input_fn(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            out("")
            raise _Quit from None

    def ask_reasons(label: str) -> list[str]:
        for i, name in enumerate(reasons, 1):
            out(f"  {i} {name:<{max(map(len, reasons))}}  {config.label_reasons[name]}")
        hint = "at least one" if label == "no" else "empty for none"
        while True:
            answer = ask(f"reasons for {label!r} (numbers, {hint}) > ")
            tokens = [t for t in re.split(r"[\s,]+", answer) if t]
            if not all(t.isdigit() and 1 <= int(t) <= len(reasons) for t in tokens):
                out(f"enter numbers from 1 to {len(reasons)}")
                continue
            if label == "no" and not tokens:
                out("a 'no' label needs at least one reason")
                continue
            return list(dict.fromkeys(reasons[int(t) - 1] for t in tokens))

    def ask_note() -> str:
        while True:
            note = ask(f"note for {NOTE_REASON!r} > ")
            if note:
                return note
            out("a note is required")

    def show(i: int, c: Candidate) -> None:
        job = c.job
        out("")
        out(f"[{i}/{stats.total}] {job_ref(job)}")
        out(job.title)
        out(f"company:  {job.company}")
        out(f"location: {job.location}" + (" [location unclear]" if c.unclear else ""))
        out(f"category: {job.category or '-'}")
        out(f"url:      {job.url}")
        if c.excluded_by:
            out(f"excluded by: {c.excluded_by[0]}: {c.excluded_by[1]}")
        out("")
        out(preview(job.description, keywords))

    try:
        for i, c in enumerate(cands, 1):
            show(i, c)
            while True:
                choice = ask(PROMPT).lower()
                if choice == "q":
                    raise _Quit
                if choice == "s":
                    stats.skipped += 1
                    break
                if choice == "d":
                    out("")
                    out(c.job.description)
                    continue
                if choice not in _CHOICES:
                    out("unknown key")
                    continue
                label = _CHOICES[choice]
                chosen = ask_reasons(label) if label != "yes" else []
                note = ask_note() if NOTE_REASON in chosen else None
                labels.set(make_label(c.job, label, chosen, note, config))
                stats.labelled += 1
                if c.excluded_by and label in ("yes", "maybe"):
                    stats.false_exclusions += 1
                break
    except _Quit:
        pass
    return stats
