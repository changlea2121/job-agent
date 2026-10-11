"""KPN's careers site (jobs.kpn.com), a recruitment-marketing CMS that the ATS
pushes vacancies into. The ATS itself is not public.

Neither public endpoint has everything: the RSS feed has descriptions and the
category ("expertise") but no location; the site's JSON API has location,
creation time and the ATS id but no description. They are joined on the site
id, which the RSS link contains (`/vacature/2041/slug`).
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Collection
from datetime import datetime
from typing import Any

from ..config import CompanyConfig
from ..html_text import html_to_text
from ..models import Job
from .http import fetch_bytes, fetch_json

DEFAULT_TIMEOUT = 30.0  # seconds
# Without X-Requested-With, query parameters make the API answer with an HTML 404.
API_PATH = "/api/vacancy/?pageSize=999"
RSS_PATH = "/feeds/rss"
_SITE_ID_RE = re.compile(r"/vacature/(\d+)(?:/|$)")
LOCATION_OPTION = "primarylocation"


class KpnAdapter:
    source = "kpn"

    def __init__(self, company: CompanyConfig, timeout: float = DEFAULT_TIMEOUT):
        self.company = company
        self.timeout = timeout

    def fetch(self, known_ids: Collection[str] = frozenset()) -> list[Job]:
        base = self.company.base_url.rstrip("/")
        api = fetch_json(base + API_PATH, timeout=self.timeout,
                         headers={"X-Requested-With": "XMLHttpRequest"})
        rss = fetch_bytes(base + RSS_PATH, timeout=self.timeout).decode("utf-8")
        return self.parse({"api": api, "rss": rss})

    def parse(self, payload: dict[str, Any]) -> list[Job]:
        api = payload["api"]
        vacancies = {v["id"]: v for v in api.get("vacancies", [])}
        hits = (api.get("meta") or {}).get("num_total_hits")
        if hits is not None and hits > len(vacancies):
            print(f"{self.company.name}: API returned {len(vacancies)} of {hits} vacancies",
                  file=sys.stderr)
        jobs, unmatched = [], []
        for item in ET.fromstring(payload["rss"]).iterfind("./channel/item"):
            link = (item.findtext("link") or "").strip()
            m = _SITE_ID_RE.search(link)
            vacancy = vacancies.get(int(m.group(1))) if m else None
            if vacancy is None:  # no ATS id or location yet; picked up next run
                unmatched.append(link)
                continue
            jobs.append(self._to_job(item, link, vacancy))
        if unmatched:
            print(f"{self.company.name}: {len(unmatched)} RSS items not in the API: "
                  f"{', '.join(unmatched)}", file=sys.stderr)
        return jobs

    def _to_job(self, item: ET.Element, link: str, vacancy: dict[str, Any]) -> Job:
        created = vacancy.get("created")
        category = (item.findtext("category") or "").strip() or None
        return Job(
            source=self.source,
            company=self.company.name,
            source_id=vacancy["external_id"],
            title=(item.findtext("title") or "").strip(),
            location=self._location(vacancy),
            url=link,
            description=html_to_text(item.findtext("description")),
            category=category if self.company.category_from == "expertise" else None,
            first_published=datetime.fromisoformat(created) if created else None,
        )

    @staticmethod
    def _location(vacancy: dict[str, Any]) -> str:
        city = next((o.get("value") for o in vacancy.get("option_values") or []
                     if (o.get("option") or {}).get("internal_name") == LOCATION_OPTION), None)
        country = (vacancy.get("country") or "").strip()  # in Dutch: "Nederland"
        return ", ".join(p.strip() for p in (city, country) if p and p.strip())
