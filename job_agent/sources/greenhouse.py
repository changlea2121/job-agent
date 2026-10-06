import json
import urllib.request
from datetime import datetime
from typing import Any

from ..config import CompanyConfig
from ..html_text import html_to_text
from ..models import Job

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
DEFAULT_TIMEOUT = 30.0  # seconds


class GreenhouseAdapter:
    source = "greenhouse"

    def __init__(self, company: CompanyConfig, timeout: float = DEFAULT_TIMEOUT):
        self.company = company
        self.timeout = timeout

    def fetch(self) -> list[Job]:
        url = API_URL.format(token=self.company.board_token)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.load(resp)
        return self.parse(payload)

    def parse(self, payload: dict[str, Any]) -> list[Job]:
        return [self._to_job(raw) for raw in payload.get("jobs", [])]

    def _to_job(self, raw: dict[str, Any]) -> Job:
        published = raw.get("first_published")
        return Job(
            source=self.source,
            company=self.company.name,
            source_id=str(raw["id"]),
            title=(raw.get("title") or "").strip(),
            location=((raw.get("location") or {}).get("name") or "").strip(),
            url=raw.get("absolute_url") or "",
            description=html_to_text(raw.get("content")),
            category=self._category(raw),
            first_published=datetime.fromisoformat(published) if published else None,
        )

    def _category(self, raw: dict[str, Any]) -> str | None:
        if self.company.category_from == "departments":
            names = [d.get("name") for d in raw.get("departments") or []]
            return ", ".join(n for n in names if n) or None
        if self.company.category_from == "metadata":
            return self._metadata_value(raw.get("metadata"))
        return None

    def _metadata_value(self, metadata: list[dict[str, Any]] | None) -> str | None:
        field = self.company.category_metadata_field
        for entry in metadata or []:
            if entry.get("name") != field:
                continue
            value = entry.get("value")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value if v)
            return str(value) if value else None
        return None
