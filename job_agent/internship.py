from dataclasses import dataclass

from .matching import keyword_pattern, normalize, validate_keywords


@dataclass(frozen=True)
class InternshipFilter:
    """Excludes internships whose description names none of
    `require_description` (case-insensitive whole words), i.e. internships
    that do not target CS, data or AI students."""

    require_description: tuple[str, ...]

    def __post_init__(self):
        value = validate_keywords(self.require_description,
                                  "internship_filter.require_description", allow_empty=False)
        object.__setattr__(self, "require_description", value)
        object.__setattr__(self, "_pattern", keyword_pattern(value))

    def excludes(self, description: str) -> bool:
        return not self._pattern.search(normalize(description))
