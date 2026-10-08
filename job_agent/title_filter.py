from dataclasses import dataclass

from .matching import keyword_pattern, normalize, validate_keywords

# Words that mark a title as Dutch, for `internship_dutch` keywords.
_DUTCH_CUE_RE = keyword_pattern((
    "m/v", "v/m", "m/v/x", "m/v/d", "stagiair", "stagiaire",
    "bij", "voor", "van", "het", "een", "en", "met",
))

_FIELDS = ("exclude_seniority", "exceptions", "internship", "internship_dutch",
           "exclude_titles")


@dataclass(frozen=True)
class TitleFilter:
    """Seniority and role exclusion and internship grouping by title keywords.

    All keywords are case-insensitive whole words. `exclude_titles` are roles
    excluded regardless of seniority ("business analyst"). `exceptions` are phrases
    removed from the title before seniority matching, so "Member of Technical
    Staff" is kept while "Staff Engineer" is excluded. `internship_dutch`
    keywords count only when the title also has a Dutch cue, because Dutch
    "stage" (internship) is an English word too ("Early-Stage").
    """

    exclude_seniority: tuple[str, ...]
    exceptions: tuple[str, ...] = ()
    internship: tuple[str, ...] = ()
    internship_dutch: tuple[str, ...] = ()
    exclude_titles: tuple[str, ...] = ()

    def __post_init__(self):
        for field in _FIELDS:
            value = validate_keywords(
                getattr(self, field), f"title_filter.{field}",
                allow_empty=field != "exclude_seniority",
            )
            object.__setattr__(self, field, value)
        object.__setattr__(self, "_seniority_re", keyword_pattern(self.exclude_seniority))
        for field in _FIELDS[1:]:
            value = getattr(self, field)
            object.__setattr__(self, f"_{field}_re", keyword_pattern(value) if value else None)

    def seniority(self, title: str) -> str | None:
        """The first seniority keyword in `title` (normalized), or None."""
        text = normalize(title)
        if self._exceptions_re is not None:
            text = self._exceptions_re.sub(" ", text)
        m = self._seniority_re.search(text)
        return " ".join(m.group(0).split()) if m else None

    def excluded_title(self, title: str) -> str | None:
        """The first `exclude_titles` keyword in `title` (normalized), or None."""
        if self._exclude_titles_re is None:
            return None
        m = self._exclude_titles_re.search(normalize(title))
        return " ".join(m.group(0).split()) if m else None

    def is_internship(self, title: str) -> bool:
        text = normalize(title)
        if self._internship_re is not None and self._internship_re.search(text):
            return True
        return bool(
            self._internship_dutch_re is not None
            and self._internship_dutch_re.search(text)
            and _DUTCH_CUE_RE.search(text)
        )
