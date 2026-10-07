import argparse
import sys
from datetime import datetime, timezone

from .config import Config, load_config
from .filtering import RULES, apply_filters
from .labels import LABELS, LabelStore, job_ref, make_label, parse_ref
from .models import Job
from .review import candidates, review
from .sources import ADAPTERS
from .storage import JobStore, utc_iso


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = JobStore(args.db)
    total_fetched = total_new = failures = 0
    try:
        store.record_run()
        for company in config.companies:
            adapter_cls = ADAPTERS.get(company.source)
            if adapter_cls is None:
                print(f"{company.name}: unknown source {company.source!r}", file=sys.stderr)
                failures += 1
                continue
            try:
                jobs = adapter_cls(company, timeout=args.timeout).fetch()
            except Exception as exc:  # keep going with the other companies
                print(f"{company.name}: fetch failed: {exc}", file=sys.stderr)
                failures += 1
                continue
            new = store.insert_new(jobs)
            total_fetched += len(jobs)
            total_new += new
            print(f"{company.name}: {len(jobs)} fetched, {new} new")
    finally:
        store.close()
    print(f"total: {total_fetched} fetched, {total_new} new")
    return 1 if failures else 0


def parse_since(value: str) -> str:
    """ISO date or datetime -> `utc_iso` string. Naive values are taken as UTC."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date or datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return utc_iso(dt)


def cmd_new(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = JobStore(args.db)
    try:
        since = args.since or store.latest_run()
        if since is None:
            print("no fetch runs recorded yet; run `fetch` first or pass --since",
                  file=sys.stderr)
            return 1
        jobs = store.jobs_since(since)
    finally:
        store.close()

    result = apply_filters(jobs, config)

    def row(job: Job, *extra: str) -> str:
        tag = " [location unclear]" if job in result.unclear else ""
        return "\t".join([job_ref(job), job.company, job.title, job.location + tag,
                          job.category or "-", job.url, *extra])

    for job in result.jobs:
        print(row(job))
    if result.internships:
        print("# internships")
        for job in result.internships:
            print(row(job))
    if args.show_excluded and result.excluded:
        print("# excluded")
        for job, rule, detail in result.excluded:
            print(row(job, f"{rule}: {detail}"))

    shown = result.jobs + result.internships
    excluded = ", ".join(f"{rule} {result.excluded_count(rule)}" for rule in RULES)
    print(f"{len(result.jobs)} new jobs, {len(result.internships)} internships "
          f"({len(result.unclear)} location unclear) since {since}; "
          f"{len(jobs)} new before filters, {len(jobs) - len(shown)} excluded "
          f"({excluded})")
    return 0


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _open_labels(config: Config, path: str) -> LabelStore:
    if not config.label_reasons:
        raise ValueError("no label_reasons in the config")
    return LabelStore(path, config.label_reasons)


def cmd_label(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    try:
        labels = _open_labels(config, args.labels)
        source, company, source_id = parse_ref(args.ref)
    except ValueError as exc:
        return _error(str(exc))
    store = JobStore(args.db)
    try:
        jobs = store.find(company, source_id, source)
    finally:
        store.close()
    if not jobs:  # no longer in jobs.db: relabel from the stored snapshot
        jobs = [l.to_job() for l in labels.find(company, source_id, source)]
    if not jobs:
        return _error(f"no job {args.ref!r} in {args.db} or {args.labels}")
    if len(jobs) > 1:
        refs = ", ".join(f"{j.source}:{j.company}:{j.source_id}" for j in jobs)
        return _error(f"{args.ref!r} is ambiguous; use one of {refs}")
    try:
        label = make_label(jobs[0], args.label, args.reason or [], args.note, config)
    except ValueError as exc:
        return _error(str(exc))
    labels.set(label)
    reasons = f" ({', '.join(label.reasons)})" if label.reasons else ""
    print(f"{label.ref}: {label.label}{reasons} [{label.filter.decision}] {label.job.title}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    if args.rule and not args.excluded:
        return _error("--rule only applies with --excluded")
    config = load_config(args.config)
    try:
        labels = _open_labels(config, args.labels)
    except ValueError as exc:
        return _error(str(exc))
    store = JobStore(args.db)
    try:
        jobs = store.jobs_since(args.since)
    finally:
        store.close()
    cands = candidates(jobs, config, labels, excluded=args.excluded, rules=args.rule)
    if not cands:
        print("nothing to review")
        return 0
    stats = review(cands, labels, config)
    summary = (f"{stats.labelled} labelled, {stats.skipped} skipped, "
               f"{stats.remaining} left unlabelled; {len(labels)} labels in {args.labels}")
    if args.excluded:
        summary += f"; {stats.false_exclusions} excluded jobs labelled yes/maybe"
    print(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch jobs for all configured companies")
    fetch.add_argument("--config", default="companies.yaml")
    fetch.add_argument("--db", default="jobs.db")
    fetch.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout (s)")
    fetch.set_defaults(func=cmd_fetch)

    new = sub.add_parser(
        "new", help="list jobs first seen in the latest fetch that pass the filters"
    )
    new.add_argument(
        "--show-excluded", action="store_true",
        help="also list excluded jobs, with the rule that excluded each",
    )
    new.add_argument("--config", default="companies.yaml")
    new.add_argument("--db", default="jobs.db")
    new.add_argument(
        "--since", type=parse_since, metavar="ISO",
        help="list jobs first seen since this date/datetime instead "
             "(e.g. 2026-10-01 or 2026-10-01T09:00+02:00; naive = UTC)",
    )
    new.set_defaults(func=cmd_new)

    label = sub.add_parser("label", help="label one job for the evaluation set")
    label.add_argument("ref", help="job ref from `new` (company:id or source:company:id)")
    label.add_argument("label", choices=LABELS)
    label.add_argument(
        "--reason", action="append", metavar="NAME",
        help="reason from label_reasons in the config; repeat for several",
    )
    label.add_argument("--note", help="short note, required with reason 'other'")
    label.add_argument("--config", default="companies.yaml")
    label.add_argument("--db", default="jobs.db")
    label.add_argument("--labels", default="labels.jsonl", help="labels file (JSON Lines)")
    label.set_defaults(func=cmd_label)

    rev = sub.add_parser(
        "review", help="label unlabelled jobs that pass the filters, one at a time"
    )
    rev.add_argument("--config", default="companies.yaml")
    rev.add_argument("--db", default="jobs.db")
    rev.add_argument("--labels", default="labels.jsonl", help="labels file (JSON Lines)")
    rev.add_argument(
        "--since", type=parse_since, metavar="ISO",
        help="only jobs first seen since this date/datetime (default: all stored jobs)",
    )
    rev.add_argument(
        "--excluded", action="store_true",
        help="review jobs removed by the filters instead, to spot false exclusions",
    )
    rev.add_argument(
        "--rule", action="append", choices=RULES,
        help="with --excluded: only jobs removed by this rule; repeat for several",
    )
    rev.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
