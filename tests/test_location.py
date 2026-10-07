from pathlib import Path

import pytest

from job_agent.config import load_config
from job_agent.location import LocationFilter, LocationMatch

CLEAR, UNCLEAR = LocationMatch.CLEAR, LocationMatch.UNCLEAR

RANDSTAD = LocationFilter(
    match=[
        "amsterdam", "amstelveen", "schiphol", "hoofddorp", "haarlemmermeer",
        "haarlem", "leiden",
        "the hague", "den haag", "'s-gravenhage", "rijswijk", "delft",
        "zoetermeer", "rotterdam", "utrecht",
    ],
    unclear=["netherlands", "nederland"],
)


def test_real_fixture_locations(nebius_location_jobs):
    got = {job.source_id: RANDSTAD.classify(job.location) for job in nebius_location_jobs}
    assert got == {
        "4981489101": CLEAR,    # Amsterdam, Netherlands; Remote - Europe
        "4724503101": UNCLEAR,  # Germany; Israel; Netherlands; Prague, ...; Remote - Europe; UK
        "4817126101": UNCLEAR,  # Netherlands; Remote - Europe
        "4965522101": None,     # Remote - Europe
        "4987727101": None,     # London, United Kingdom; Remote - Europe
    }


# Synthetic strings: shapes our current boards don't produce yet.
@pytest.mark.parametrize("location, expected", [
    ("Amsterdam", CLEAR),
    ("AMSTERDAM, NL", CLEAR),
    ("Hoofddorp, Netherlands", CLEAR),
    ("The Hague, Netherlands", CLEAR),
    ("Den Haag", CLEAR),
    ("'s-Gravenhage", CLEAR),
    ("’s-Gravenhage, Zuid-Holland", CLEAR),  # curly apostrophe
    ("Berlin; Rotterdam", CLEAR),
    ("Utrecht; Netherlands", CLEAR),              # a clear part wins
    ("Netherlands", UNCLEAR),
    ("The Netherlands", UNCLEAR),
    ("Remote - Netherlands", UNCLEAR),
    ("Netherlands (Remote)", UNCLEAR),
    ("Remote, The Netherlands", UNCLEAR),
    ("Hybrid - Nederland", UNCLEAR),
    ("Eindhoven, Netherlands", None),             # names a non-Randstad city
    ("Remote - Netherlands, Eindhoven", None),
    ("Remote - Europe", None),
    ("Remote", None),
    ("Haarlemmermeer", CLEAR),
    ("Delfts Blauw", None),                       # whole words only
    ("Haarlemmerliede", None),                    # "haarlem" is not a prefix match
    ("", None),
])
def test_classify(location, expected):
    assert RANDSTAD.classify(location) == expected


def test_without_unclear_keywords_netherlands_is_excluded():
    assert LocationFilter(match=["amsterdam"]).classify("Netherlands") is None


@pytest.mark.parametrize("kwargs, message", [
    ({"match": []}, "match must not be empty"),
    ({"match": "amsterdam"}, "match must be a list"),
    ({"match": ["amsterdam", ""]}, "non-empty strings"),
    ({"match": ["amsterdam"], "unclear": [3]}, "non-empty strings"),
])
def test_invalid_filter_raises(kwargs, message):
    with pytest.raises(ValueError, match=message):
        LocationFilter(**kwargs)


def test_config_rejects_unknown_filter_keys(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("location_filter:\n  match: [amsterdam]\n  matches: [delft]\n")
    with pytest.raises(ValueError, match="unknown keys"):
        load_config(path)


def test_repo_config_filter_loads():
    config = load_config(Path(__file__).parent.parent / "companies.yaml")
    assert config.location_filter is not None
    assert config.location_filter.classify("'s-Gravenhage") is CLEAR
