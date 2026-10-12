"""Workday careers sites, through the unofficial JSON API the Workday front end
uses (`/wday/cxs/{tenant}/{site}`). It is undocumented and may change.

Listings carry no description, date or category, so each new job needs a
detail request, and the category comes from re-running the listing once per
job family group facet. Details are only fetched for jobs not stored yet.
"""
import sys
import time
from collections.abc import Callable, Collection, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from ..config import CompanyConfig
from ..html_text import html_to_text
from ..models import Job
from .http import fetch_json

DEFAULT_TIMEOUT = 30.0  # seconds
PAGE_SIZE = 20  # the API rejects larger pages
MAX_WORKERS = 4  # parallel detail requests
CATEGORY_FACET = "jobFamilyGroup"
# startDate is a date only; ING posts from Amsterdam.
POSTING_TZ = ZoneInfo("Europe/Amsterdam")


def listing_req_id(listing: dict[str, Any]) -> str | None:
    """The requisition id (`jobReqId` in the detail) shown in a listing."""
    fields = listing.get("bulletFields") or []
    return fields[0] if fields else None


def _describe(exc: Exception) -> str:
    # A bare KeyError prints as just "'externalPath'".
    return f"{type(exc).__name__}: {exc}"


@contextmanager
def _step(what: str) -> Iterator[None]:
    """Name the step (listing page, category facet, detail) in any error."""
    try:
        yield
    except Exception as exc:
        raise RuntimeError(f"{what}: {_describe(exc)}") from exc


class WorkdayAdapter:
    source = "workday"

    def __init__(self, company: CompanyConfig, timeout: float = DEFAULT_TIMEOUT,
                 sleep: Callable[[float], None] = time.sleep):
        self.company = company
        self.timeout = timeout
        self.sleep = sleep
        host = company.workday_host
        tenant = host.split(".", 1)[0]
        self.api = f"https://{host}/wday/cxs/{tenant}/{company.workday_site}"

    def _get(self, path: str) -> Any:
        return fetch_json(self.api + path, timeout=self.timeout, sleep=self.sleep)

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        return fetch_json(self.api + path, data=body, timeout=self.timeout, sleep=self.sleep)

    def fetch(self, known_ids: Collection[str] = frozenset()) -> list[Job]:
        listings, categories = self.list_postings()
        todo = [l for l in listings if listing_req_id(l) not in known_ids]
        paths = [l["externalPath"] for l in todo]
        with ThreadPoolExecutor(MAX_WORKERS) as pool:
            details = list(pool.map(self._detail, paths))
        postings = [
            {"category": categories.get(p), "path": p, "detail": d}
            for p, d in zip(paths, details) if d is not None
        ]
        return self.parse({"postings": postings})

    def _detail(self, path: str) -> dict[str, Any] | None:
        try:
            return self._get(path)
        except Exception as exc:  # skip it; it is still new on the next run
            print(f"{self.company.name}: skipped detail {path}: {_describe(exc)}",
                  file=sys.stderr)
            return None

    def list_postings(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """All listings, and their category by externalPath.

        With a category configured, the listing is run once per job family
        group. Jobs without one (if the counts fall short of the total) come
        from a plain listing afterwards.

        Some listings are stubs with only `bulletFields` (the requisition id):
        no path, title or location, also when searched for by id. They cannot
        be fetched, so they are skipped with a warning, unless more than
        `workday_max_stub_share` of all entries are stubs: then the format
        has probably changed and the company fails.
        """
        first = self._page({}, 0, "listing")
        listings: dict[str, dict[str, Any]] = {}
        categories: dict[str, str] = {}
        stubs: dict[str, str] = {}  # requisition id of a listing without a path -> where

        def add(listing: dict[str, Any], where: str, category: str | None = None) -> None:
            path = listing.get("externalPath")
            if not path:
                stubs.setdefault(listing_req_id(listing) or repr(listing), where)
                return
            listings.setdefault(path, listing)
            if category is not None:
                categories[path] = category

        if self.company.category_from == "job_family_group":
            with _step(f"category facet {CATEGORY_FACET}"):
                facet = next((f for f in first.get("facets", [])
                              if f.get("facetParameter") == CATEGORY_FACET), {})
                values = [(v["id"], v["descriptor"]) for v in facet.get("values", [])]
            for value_id, name in values:
                where = f"listing ({CATEGORY_FACET} {name!r})"
                for listing in self._all_pages({CATEGORY_FACET: [value_id]}, where):
                    add(listing, where, name)
        # Stubs count as listed, or they would force the plain pass every run.
        if len(listings) + len(stubs) < first.get("total", 0):
            for listing in self._all_pages({}, "listing", first):
                add(listing, "listing")
        self._check_stubs(stubs, len(listings) + len(stubs))
        return list(listings.values()), categories

    def _check_stubs(self, stubs: dict[str, str], entries: int) -> None:
        """Warn about each stub, or fail if there are too many to be odd ones."""
        limit = self.company.workday_max_stub_share
        if stubs and len(stubs) > limit * entries:
            raise RuntimeError(
                f"listing: {len(stubs)} of {entries} entries have no externalPath "
                f"({len(stubs) / entries:.0%}, more than workday_max_stub_share "
                f"{limit:.0%}); the API format has probably changed. "
                f"First: {', '.join(list(stubs)[:3])}")
        for req, where in stubs.items():
            print(f"{self.company.name}: skipped {where} entry without "
                  f"externalPath: {req}", file=sys.stderr)

    def _page(self, facets: dict[str, list[str]], offset: int, where: str) -> dict[str, Any]:
        with _step(f"{where} page at offset {offset}"):
            return self._post("/jobs", {"appliedFacets": facets, "limit": PAGE_SIZE,
                                        "offset": offset, "searchText": ""})

    def _all_pages(self, facets: dict[str, list[str]], where: str,
                   first: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        # Only the first page's `total` is reliable; later pages may report 0.
        page = first or self._page(facets, 0, where)
        total, found = page.get("total", 0), list(page.get("jobPostings", []))
        while page.get("jobPostings") and len(found) < total:
            page = self._page(facets, len(found), where)
            found += page.get("jobPostings", [])
        return found

    def parse(self, payload: dict[str, Any]) -> list[Job]:
        jobs = []
        for posting in payload.get("postings", []):
            with _step(f"detail {posting.get('path') or '(unknown path)'}"):
                jobs.append(self._to_job(posting))
        return jobs

    def _to_job(self, posting: dict[str, Any]) -> Job:
        info = posting["detail"]["jobPostingInfo"]
        start = info.get("startDate")
        return Job(
            source=self.source,
            company=self.company.name,
            source_id=info["jobReqId"],
            title=(info.get("title") or "").strip(),
            location=self._location(info),
            url=info.get("externalUrl") or "",
            description=html_to_text(info.get("jobDescription")),
            category=(posting.get("category")
                      if self.company.category_from == "job_family_group" else None),
            first_published=(datetime.combine(date.fromisoformat(start), dtime(),
                                              POSTING_TZ) if start else None),
        )

    @staticmethod
    def _location(info: dict[str, Any]) -> str:
        """"CDR (Amsterdam - Cedar), Netherlands; HBP (...)": the country is
        only given for the primary location."""
        primary = (info.get("location") or "").strip()
        country = (info.get("country") or {}).get("descriptor")
        parts = [f"{primary}, {country}" if primary and country else primary or country or ""]
        parts += [l.strip() for l in info.get("additionalLocations") or [] if l.strip()]
        return "; ".join(p for p in parts if p)
