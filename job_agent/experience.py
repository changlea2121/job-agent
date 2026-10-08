"""Required years of experience, extracted from a job description.

Lines are matched one at a time (html_to_text puts each bullet on its own
line). A mention counts as a hard requirement unless it is in a nice-to-have
section, softened in its own clause ("ideally 4+ years", "3+ years is a plus"),
or a degree other than a PhD can replace it ("3+ years or an MSc").
"""
import re
from dataclasses import dataclass

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
    "een": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7,
    "acht": 8, "negen": 9, "tien": 10,
}
_NUM = r"(\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
MAX_YEARS = 15  # more is company history ("20 years of payments data")

# "5+ years", "3-5 years", "3 to 5 years", "5 or more years", "2 tot 4 jaar"
_YEARS_RE = re.compile(
    rf"(?<![\w$€£.,]){_NUM}\s*(?:\+|plus)?\s*(?:(?:-|–|—|to|tot)\s*{_NUM}\s*\+?\s*)?"
    rf"(?:or more\s+|of meer\s+)?(?:years?|yrs?|jaar|jaren)(?!\w)",
    re.I,
)
# The years are experience if the line says so, or if what follows says what
# they were spent on ("3+ years administering Entra ID").
_EXPERIENCE_RE = re.compile(r"experience|ervaring|track record|background", re.I)
_SPENT_ON_RE = re.compile(
    r"\s*(?:of|in|as|at|with|\w+ing|relevant|professional|industry|hands-on|"
    r"post|full-time|ervaring|werkervaring)\b", re.I)
# Right before the years: a timeframe ("medium-term (1-3 years)", "within 2 years").
_TIMEFRAME_RE = re.compile(
    r"(?:\b(?:within|past|last|next|over the|in less than|less than|for the|term|"
    r"after|every|up to|binnen|afgelopen)|-term)\s*\(?\s*$", re.I)
# Softeners in the same clause, before the years or after them. "5+ years,
# ideally in fintech" softens the domain, not the years.
_SOFT_BEFORE_RE = re.compile(r"\b(?:ideally|preferably|bonus|bij voorkeur|liefst)\b", re.I)
_SOFT_AFTER_RE = re.compile(
    r"\b(?:is a plus|a plus|preferred|nice to have|nice-to-have|desirable|"
    r"an advantage|is een pre|pluspunt)\b", re.I)
# Section headings that make the bullets below them optional.
_OPTIONAL_HEADING_RE = re.compile(
    r"nice[ -]to[ -]have|bonus|preferred|pluspunt|would be (?:great|nice)|"
    r"(?:will|would) be an added|stand out|optional|strong candidates may also", re.I)
_HEADING_MAX_CHARS = 80
# Degrees that can replace the years. A PhD-only alternative still blocks.
_DEGREE_RE = re.compile(
    r"\b(?:master|msc|m\.sc|bachelor|bsc|b\.sc|degree|diploma|hbo|wo)\b", re.I)
_PHD_DEGREE_RE = re.compile(r"\b(?:phd|ph\.d|doctoral|doctorate)\s+degree\b", re.I)
# "or"; Dutch "of" only right before a degree, since English "of" is everywhere.
_OR_RE = re.compile(
    r"\bor\b|\bof\s+(?=(?:een\s+)?(?:afgeronde\s+)?(?:master|bachelor|msc|bsc|hbo|wo)\b)",
    re.I)
# "... or [at least] 3+ years": the "or" directly precedes the years.
_OR_BEFORE_YEARS_RE = re.compile(
    r"\bor\s+(?:at least\s+|a minimum of\s+|minimum\s+|minimaal\s+)?$", re.I)


@dataclass(frozen=True)
class Mention:
    line: str
    years: int  # the minimum asked for: the lower bound of a range
    optional: bool  # nice-to-have section, or softened in its clause
    degree_alternative: bool  # a non-PhD degree can replace the years

    @property
    def blocking(self) -> bool:
        return not self.optional and not self.degree_alternative


def _num(text: str) -> int:
    return int(text) if text.isdigit() else _NUM_WORDS[text.lower()]


def _clause_bounds(line: str, start: int, end: int) -> tuple[int, int]:
    """Bounds of the clause around [start, end), split at ; . , ( )."""
    left = max(line.rfind(c, 0, start) for c in ";.,()") + 1
    rights = [i for i in (line.find(c, end) for c in ";.,()") if i != -1]
    return left, min(rights) if rights else len(line)


def _offers_degree(text: str) -> bool:
    return bool(_DEGREE_RE.search(_PHD_DEGREE_RE.sub(" ", text)))


def _degree_alternative(line: str, start: int, end: int) -> bool:
    """'3+ years [...], or an MSc' in the same sentence, or 'an MSc or 3+ years'
    in the same clause. The degree must directly follow its "or": in "5+ years
    of Java or Kotlin, and a degree", the degree is an extra requirement."""
    after = re.split(r"[.;]", line[end:], maxsplit=1)[0]
    for m in _OR_RE.finditer(after):
        if _offers_degree(re.split(r"[,()]", after[m.end():], maxsplit=1)[0]):
            return True
    left, _ = _clause_bounds(line, start, end)
    before = line[left:start]
    m = _OR_BEFORE_YEARS_RE.search(before)
    return bool(m) and _offers_degree(before[:m.start()])


def mentions(description: str) -> list[Mention]:
    found, in_optional = [], False
    for raw in description.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_bullet = line[0] in "-–•*"
        if not is_bullet and len(line) <= _HEADING_MAX_CHARS and not _YEARS_RE.search(line):
            in_optional = bool(_OPTIONAL_HEADING_RE.search(line))  # a section heading
            continue
        for m in _YEARS_RE.finditer(line):
            years = _num(m.group(1))
            if not 1 <= years <= MAX_YEARS or _TIMEFRAME_RE.search(line[:m.start()]):
                continue
            if not (_SPENT_ON_RE.match(line, m.end()) or _EXPERIENCE_RE.search(line)):
                continue
            left, right = _clause_bounds(line, m.start(), m.end())
            softened = (_SOFT_BEFORE_RE.search(line[left:m.start()])
                        or _SOFT_AFTER_RE.search(line[m.end():right]))
            found.append(Mention(
                line=line, years=years, optional=in_optional or bool(softened),
                degree_alternative=_degree_alternative(line, m.start(), m.end()),
            ))
    return found


def required_years(description: str) -> int | None:
    """The highest blocking requirement in years, or None if there is none."""
    years = [m.years for m in mentions(description) if m.blocking]
    return max(years) if years else None


@dataclass(frozen=True)
class ExperienceFilter:
    """Excludes jobs that require at least `min_years` of experience."""

    min_years: int = 3

    def __post_init__(self):
        if isinstance(self.min_years, bool) or not isinstance(self.min_years, int) \
                or self.min_years < 1:
            raise ValueError(
                f"experience_filter.min_years must be a positive integer, "
                f"got {self.min_years!r}"
            )

    def excluded_years(self, description: str) -> int | None:
        """The required years if they reach `min_years`, else None."""
        years = required_years(description)
        return years if years is not None and years >= self.min_years else None
