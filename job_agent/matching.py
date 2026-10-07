import re


def normalize(text: str) -> str:
    return text.replace("’", "'").casefold()


def keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Case-insensitive whole-word match for any keyword (search normalized text).

    Lookarounds instead of \\b so keywords starting with "'" ("'s-gravenhage")
    still match after a space. Spaces inside a phrase match any whitespace.
    """
    alternatives = "|".join(
        r"\s+".join(re.escape(word) for word in normalize(k).split()) for k in keywords
    )
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


def validate_keywords(value, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    """Check a config keyword list; return it as a tuple of stripped strings."""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list of strings")
    if not all(isinstance(k, str) and k.strip() for k in value):
        raise ValueError(f"{name} must contain only non-empty strings")
    if not value and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    return tuple(k.strip() for k in value)
