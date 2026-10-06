from dataclasses import dataclass
from pathlib import Path

import yaml

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


def load_companies(path: str | Path) -> list[CompanyConfig]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [CompanyConfig(**entry) for entry in data.get("companies", [])]
