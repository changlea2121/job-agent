import re
from dataclasses import dataclass
from enum import Enum

from .matching import keyword_pattern as _keyword_pattern
from .matching import normalize as _normalize
from .matching import validate_keywords

# Words that may surround an "unclear" keyword without naming a place, e.g.
# "Remote - Netherlands" or "The Netherlands (Hybrid)".
_FILLER_WORDS = ("remote", "hybrid", "the")


class LocationMatch(Enum):
    CLEAR = "clear"
    UNCLEAR = "unclear"  # only a country-level hint, e.g. "Netherlands"


@dataclass(frozen=True)
class LocationFilter:
    """Classifies a job location string against configured keywords.

    The location is split on ";" (Greenhouse lists multiple locations that
    way). A part is CLEAR if it contains a `match` keyword as a whole word,
    and UNCLEAR if it consists only of an `unclear` keyword plus filler such
    as "Remote -". "Eindhoven, Netherlands" is neither: it names a city.
    The job takes the best result over its parts; None means excluded.
    """

    match: tuple[str, ...]
    unclear: tuple[str, ...] = ()

    def __post_init__(self):
        for field in ("match", "unclear"):
            value = validate_keywords(
                getattr(self, field), f"location_filter.{field}",
                allow_empty=field != "match",
            )
            object.__setattr__(self, field, value)
        object.__setattr__(self, "_match_re", _keyword_pattern(self.match))
        object.__setattr__(
            self, "_unclear_re", _keyword_pattern(self.unclear) if self.unclear else None
        )

    def classify(self, location: str) -> LocationMatch | None:
        parts = [_normalize(p).strip() for p in location.split(";")]
        if any(self._match_re.search(p) for p in parts):
            return LocationMatch.CLEAR
        if any(self._is_unclear(p) for p in parts):
            return LocationMatch.UNCLEAR
        return None

    def _is_unclear(self, part: str) -> bool:
        if self._unclear_re is None or not self._unclear_re.search(part):
            return False
        rest = self._unclear_re.sub(" ", part)
        rest = re.sub(rf"(?<!\w)(?:{'|'.join(_FILLER_WORDS)})(?!\w)", " ", rest)
        return not re.search(r"\w", rest)
