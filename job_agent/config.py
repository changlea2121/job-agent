from dataclasses import dataclass
from pathlib import Path

import yaml

from .location import LocationFilter

CATEGORY_SOURCES = ("metadata", "departments")


@dataclass(frozen=True)
class CompanyConfig:
    name: str
    source: str
    board_token: str
    # Where Job.category comes from: "metadata" (needs category_metadata_field),
    # "departments", or None for no category. Defaults to "metadata" when a
    # metadata field is given.
    category_from: str | None = None
    category_metadata_field: str | None = None

    def __post_init__(self):
        if self.category_from is None and self.category_metadata_field:
            object.__setattr__(self, "category_from", "metadata")
        if self.category_from not in (None, *CATEGORY_SOURCES):
            raise ValueError(
                f"{self.name}: category_from must be one of {CATEGORY_SOURCES}, "
                f"got {self.category_from!r}"
            )
        if self.category_from == "metadata" and not self.category_metadata_field:
            raise ValueError(
                f"{self.name}: category_from 'metadata' requires category_metadata_field"
            )


@dataclass(frozen=True)
class Config:
    companies: list[CompanyConfig]
    location_filter: LocationFilter | None  # None: no location filtering


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    companies = [CompanyConfig(**entry) for entry in data.get("companies", [])]
    raw_filter = data.get("location_filter")
    if raw_filter is not None and not isinstance(raw_filter, dict):
        raise ValueError("location_filter must be a mapping with 'match' and 'unclear'")
    unknown = set(raw_filter or {}) - {"match", "unclear"}
    if unknown:
        raise ValueError(f"location_filter: unknown keys {sorted(unknown)}")
    location_filter = LocationFilter(**raw_filter) if raw_filter is not None else None
    return Config(companies=companies, location_filter=location_filter)
