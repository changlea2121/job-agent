import argparse
import sys
from datetime import datetime, timezone

from .config import load_config
from .location import LocationMatch
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

    clear, unclear = [], []
    for job in jobs:
        if config.location_filter is None:
            clear.append(job)
            continue
        match = config.location_filter.classify(job.location)
        if match is LocationMatch.CLEAR:
            clear.append(job)
        elif match is LocationMatch.UNCLEAR:
            unclear.append(job)

    rows = [(job, "") for job in clear] + [(job, " [location unclear]") for job in unclear]
    for job, tag in rows:
        print("\t".join([job.company, job.title, job.location + tag,
                         job.category or "-", job.url]))
    print(f"{len(clear) + len(unclear)} new jobs ({len(unclear)} location unclear) "
          f"since {since}; {len(jobs)} new before location filter")
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
        "new", help="list jobs first seen in the latest fetch that pass the location filter"
    )
    new.add_argument("--config", default="companies.yaml")
    new.add_argument("--db", default="jobs.db")
    new.add_argument(
        "--since", type=parse_since, metavar="ISO",
        help="list jobs first seen since this date/datetime instead "
             "(e.g. 2026-10-01 or 2026-10-01T09:00+02:00; naive = UTC)",
    )
    new.set_defaults(func=cmd_new)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
