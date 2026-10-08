"""Summary of the labels file: per label, reason, company and filter decision."""
from collections import Counter
from collections.abc import Iterable

from .filtering import RULES
from .labels import LABELS, Label


def _table(header: list[str], rows: list[list]) -> list[str]:
    cells = [header, *[[str(c) for c in row] for row in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(header))]
    return ["  ".join(c.ljust(w) if i == 0 else c.rjust(w)
                      for i, (c, w) in enumerate(zip(row, widths)))
            for row in cells]


def _by_label(labels: list[Label], key) -> list[list]:
    """Rows of [group, total, yes, maybe, no], in first-seen order of `key`."""
    counts = Counter((key(l), l.label) for l in labels)
    groups = list(dict.fromkeys(key(l) for l in labels))
    return [[g, sum(counts[g, x] for x in LABELS), *(counts[g, x] for x in LABELS)]
            for g in groups]


def format_stats(labels: Iterable[Label], reasons: Iterable[str]) -> list[str]:
    labels = sorted(labels, key=lambda l: l.key)
    if not labels:
        return ["no labels"]
    out = [f"{len(labels)} labels", ""]

    per_label = Counter(l.label for l in labels)
    out += _table(["label", "count"], [[x, per_label[x]] for x in LABELS]) + [""]

    # Every configured reason, so unused ones show as 0.
    per_reason = Counter(r for l in labels for r in l.reasons)
    out += _table(["reason", "count"], [[r, per_reason[r]] for r in reasons])
    no_reason = sum(1 for l in labels if l.label == "maybe" and not l.reasons)
    out += [f"(maybe without a reason: {no_reason})", ""]

    header = ["", "total", *LABELS]
    by_company = sorted(_by_label(labels, lambda l: l.company), key=lambda r: -r[1])
    out += _table(["company", *header[1:]], by_company) + [""]

    def decision(l: Label) -> str:
        return "kept" if l.filter.decision == "kept" else f"excluded: {l.filter.rule}"

    rows = _by_label(labels, decision)
    order = ["kept", *(f"excluded: {r}" for r in RULES)]
    rows.sort(key=lambda r: order.index(r[0]) if r[0] in order else len(order))
    excluded = [r for r in rows if r[0] != "kept"]
    if excluded:
        rows.append(["excluded (all)", *(sum(r[i] for r in excluded) for i in range(1, 5))])
    else:
        rows.append(["excluded", 0, 0, 0, 0])
    out += _table(["filter at labelling", *header[1:]], rows)
    return out
