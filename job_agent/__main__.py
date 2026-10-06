import argparse
import sys

from .config import load_companies
from .sources import ADAPTERS
from .storage import JobStore


def cmd_fetch(args: argparse.Namespace) -> int:
    companies = load_companies(args.config)
    store = JobStore(args.db)
    total_fetched = total_new = failures = 0
    try:
        for company in companies:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch jobs for all configured companies")
    fetch.add_argument("--config", default="companies.yaml")
    fetch.add_argument("--db", default="jobs.db")
    fetch.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout (s)")
    fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
