from dataclasses import dataclass, field

from .config import Config
from .location import LocationMatch
from .models import Job

RULES = ("location", "category", "seniority", "title")


@dataclass
class FilterResult:
    jobs: list[Job] = field(default_factory=list)
    internships: list[Job] = field(default_factory=list)
    unclear: set[Job] = field(default_factory=set)  # jobs whose location is unclear
    excluded: list[tuple[Job, str, str]] = field(default_factory=list)  # (job, rule, detail)

    def excluded_count(self, rule: str) -> int:
        return sum(1 for _, r, _ in self.excluded if r == rule)


def apply_filters(jobs: list[Job], config: Config) -> FilterResult:
    """Apply the output-time rules in order; each excluded job gets the first
    rule that removed it. Internships among the rest are listed separately.
    Clear locations come before unclear ones within each list."""
    result = FilterResult()
    clear, unclear = [], []
    for job in jobs:
        match = LocationMatch.CLEAR
        if config.location_filter is not None:
            match = config.location_filter.classify(job.location)
        if match is None:
            result.excluded.append((job, "location", job.location))
            continue
        company = config.company(job.company)
        if company is not None and company.excludes_category(job.category):
            result.excluded.append((job, "category", job.category))
            continue
        title_filter = config.title_filter
        keyword = title_filter.seniority(job.title) if title_filter else None
        if keyword is not None:
            result.excluded.append((job, "seniority", keyword))
            continue
        keyword = title_filter.excluded_title(job.title) if title_filter else None
        if keyword is not None:
            result.excluded.append((job, "title", keyword))
            continue
        if match is LocationMatch.UNCLEAR:
            result.unclear.add(job)
            unclear.append(job)
        else:
            clear.append(job)

    for job in clear + unclear:
        intern = config.title_filter is not None and config.title_filter.is_internship(job.title)
        (result.internships if intern else result.jobs).append(job)
    return result
