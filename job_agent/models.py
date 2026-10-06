from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Job:
    source: str
    company: str
    source_id: str
    title: str
    location: str
    url: str
    description: str  # plain text
    category: str | None
    first_published: datetime | None  # timezone-aware; used for recency
