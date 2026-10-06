import json
from pathlib import Path

import pytest

from job_agent.config import CompanyConfig
from job_agent.sources.greenhouse import GreenhouseAdapter

FIXTURES = Path(__file__).parent / "fixtures"

ADYEN = CompanyConfig(
    name="adyen", source="greenhouse", board_token="adyen",
    category_from="departments",
)
NEBIUS = CompanyConfig(
    name="nebius", source="greenhouse", board_token="nebius",
    category_metadata_field="Job Category",
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def adyen_jobs():
    return GreenhouseAdapter(ADYEN).parse(load_fixture("greenhouse_adyen.json"))


@pytest.fixture
def nebius_jobs():
    return GreenhouseAdapter(NEBIUS).parse(load_fixture("greenhouse_nebius.json"))
