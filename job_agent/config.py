import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .location import LocationFilter
from .matching import validate_keywords
from .title_filter import TitleFilter

CATEGORY_SOURCES = ("metadata", "departments")
_REASON_NAME_RE = re.compile(r"[a-z0-9_]+")


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
    # Categories hidden by `job_agent new`; exact match, case-insensitive.
    exclude_categories: tuple[str, ...] = ()

    def __post_init__(self):
        try:
            categories = validate_keywords(self.exclude_categories, "exclude_categories")
        except ValueError as exc:
            raise ValueError(f"{self.name}: {exc}") from None
        object.__setattr__(self, "exclude_categories", categories)
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

    def excludes_category(self, category: str | None) -> bool:
        if category is None:
            return False
        return category.casefold() in {c.casefold() for c in self.exclude_categories}


@dataclass(frozen=True)
class Config:
    companies: list[CompanyConfig]
    location_filter: LocationFilter | None  # None: no location filtering
    title_filter: TitleFilter | None = None  # None: no seniority or internship rules
    # Reasons usable when labelling, name -> description, in display order.
    label_reasons: dict[str, str] = field(default_factory=dict)
    # Words whose description lines `review` shows first.
    preview_keywords: tuple[str, ...] = ()

    def company(self, name: str) -> CompanyConfig | None:
        return next((c for c in self.companies if c.name == name), None)


def _load_label_reasons(raw) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise ValueError("label_reasons must be a non-empty mapping of name to description")
    reasons = {}
    for name, description in raw.items():
        if not isinstance(name, str) or not _REASON_NAME_RE.fullmatch(name):
            raise ValueError(
                f"label_reasons: invalid name {name!r} (use lowercase letters, digits and _)"
            )
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"label_reasons.{name}: description must be a non-empty string")
        reasons[name] = description.strip()
    return reasons


def _load_section(data: dict, name: str, cls, keys: tuple[str, ...]):
    raw = data.get(name)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a mapping with {', '.join(map(repr, keys))}")
    unknown = set(raw) - set(keys)
    if unknown:
        raise ValueError(f"{name}: unknown keys {sorted(unknown)}")
    return cls(**raw)


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    companies = [CompanyConfig(**entry) for entry in data.get("companies", [])]
    return Config(
        companies=companies,
        location_filter=_load_section(
            data, "location_filter", LocationFilter, ("match", "unclear")
        ),
        title_filter=_load_section(
            data, "title_filter", TitleFilter,
            ("exclude_seniority", "exceptions", "internship", "internship_dutch"),
        ),
        label_reasons=_load_label_reasons(data.get("label_reasons")),
        preview_keywords=validate_keywords(
            data.get("preview_keywords", []), "preview_keywords"
        ),
    )
