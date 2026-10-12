from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import load_fixture
from job_agent.config import CompanyConfig
from job_agent.sources.workday import WorkdayAdapter

ING = CompanyConfig(
    name="ing", source="workday", workday_host="ing.wd3.myworkdayjobs.com",
    workday_site="ICSGBLCOR", category_from="job_family_group",
)


@pytest.fixture
def ing_jobs():
    return WorkdayAdapter(ING).parse(load_fixture("workday_ing.json"))


def test_maps_core_fields(ing_jobs):
    job = ing_jobs[0]
    assert job.source == "workday"
    assert job.company == "ing"
    assert job.source_id == "REQ-10122547"
    assert job.title == "Senior Software Engineer"
    assert job.url == ("https://ing.wd3.myworkdayjobs.com/ICSGBLCOR/job/AME-Amsterdam---Maple/"
                       "Senior-Software-Engineer_REQ-10122547-1")
    assert job.category == "Tech"


def test_location_has_country_and_additional_locations(ing_jobs):
    assert ing_jobs[0].location == "AME (Amsterdam - Maple), Netherlands"
    assert ing_jobs[2].location == ("WP (Rotterdam - Wilgenplas), Netherlands; "
                                    "HBP (Amsterdam - Haarlerbergpark)")


def test_first_published_is_start_date_in_amsterdam(ing_jobs):
    assert ing_jobs[1].first_published == datetime(2026, 8, 14, tzinfo=ZoneInfo("Europe/Amsterdam"))


def test_description_is_plain_text(ing_jobs):
    for job in ing_jobs:
        assert job.description and "<" not in job.description
    assert "Java" in ing_jobs[0].description
    assert "Nederlands" in ing_jobs[1].description  # Dutch posting


def test_category_none_when_not_configured():
    company = CompanyConfig(name="ing", source="workday",
                            workday_host="ing.wd3.myworkdayjobs.com", workday_site="ICSGBLCOR")
    jobs = WorkdayAdapter(company).parse(load_fixture("workday_ing.json"))
    assert all(j.category is None for j in jobs)


@pytest.mark.parametrize("missing", ["workday_host", "workday_site"])
def test_config_requires_host_and_site(missing):
    kwargs = {"workday_host": "ing.wd3.myworkdayjobs.com", "workday_site": "ICSGBLCOR"}
    del kwargs[missing]
    with pytest.raises(ValueError, match=f"^ing: source 'workday' requires {missing}"):
        CompanyConfig(name="ing", source="workday", **kwargs)


def test_config_rejects_greenhouse_category_source():
    with pytest.raises(ValueError, match="category_from for source 'workday'"):
        CompanyConfig(name="ing", source="workday", workday_host="h", workday_site="s",
                      category_from="departments")


class FakeWorkday(WorkdayAdapter):
    """Serves listings and details from memory, recording the requests."""

    def __init__(self, company, jobs, families):
        super().__init__(company)
        self.jobs = jobs  # externalPath -> (req id, family id or None)
        self.families = families  # family id -> name
        self.posts, self.gets = [], []

    def _post(self, path, body):
        assert path == "/jobs" and body["limit"] == 20
        self.posts.append(body)
        family = body["appliedFacets"].get("jobFamilyGroup", [None])[0]
        # A path starting with "stub" is listed like Workday's stubs: no externalPath.
        rows = [{"bulletFields": [req]} if p.startswith("stub") else
                {"externalPath": p, "bulletFields": [req]}
                for p, (req, fam) in self.jobs.items() if family is None or fam == family]
        page = rows[body["offset"]:body["offset"] + 20]
        values = [{"id": f, "descriptor": n,
                   "count": sum(fam == f for _, fam in self.jobs.values())}
                  for f, n in self.families.items()]
        # Like Workday, only the first page reports the total.
        return {"total": len(rows) if body["offset"] == 0 else 0, "jobPostings": page,
                "facets": [{"facetParameter": "jobFamilyGroup", "values": values}]}

    def _get(self, path):
        self.gets.append(path)
        req, _ = self.jobs[path]
        return {"jobPostingInfo": {"jobReqId": req, "title": path, "location": "X",
                                   "startDate": "2026-10-01", "externalUrl": path}}


def _jobs(n, family):
    return {f"/job/{family}-{i}": (f"REQ-{family}-{i}", family) for i in range(n)}


def test_fetch_pages_each_family_and_skips_known_details():
    jobs = {**_jobs(25, "tech"), **_jobs(3, "hr")}
    adapter = FakeWorkday(ING, jobs, {"tech": "Tech", "hr": "HR"})
    got = adapter.fetch(known_ids={"REQ-tech-0", "REQ-hr-1"})
    assert len(got) == 26
    assert {j.category for j in got} == {"Tech", "HR"}
    assert "/job/tech-0" not in adapter.gets and len(adapter.gets) == 26
    # One plain page, two pages of tech, one of hr; no fallback pass needed.
    assert [(b["appliedFacets"], b["offset"]) for b in adapter.posts] == [
        ({}, 0), ({"jobFamilyGroup": ["tech"]}, 0), ({"jobFamilyGroup": ["tech"]}, 20),
        ({"jobFamilyGroup": ["hr"]}, 0),
    ]


def test_fetch_lists_jobs_without_a_family_too():
    jobs = {**_jobs(2, "tech"), "/job/none": ("REQ-none", None)}
    adapter = FakeWorkday(ING, jobs, {"tech": "Tech"})
    got = {j.source_id: j.category for j in adapter.fetch()}
    assert got == {"REQ-tech-0": "Tech", "REQ-tech-1": "Tech", "REQ-none": None}


def test_failed_detail_is_skipped(capsys):
    adapter = FakeWorkday(ING, _jobs(2, "tech"), {"tech": "Tech"})
    real_get = adapter._get

    def flaky(path):
        if path.endswith("-1"):
            raise OSError("boom")
        return real_get(path)

    adapter._get = flaky
    assert [j.source_id for j in adapter.fetch()] == ["REQ-tech-0"]
    assert "ing: skipped detail /job/tech-1: OSError: boom" in capsys.readouterr().err


class ListingFixture(WorkdayAdapter):
    """Serves a saved listing page; details are made up from the path."""

    def __init__(self, company, page):
        super().__init__(company)
        self.page, self.gets = page, []

    def _post(self, path, body):
        return self.page

    def _get(self, path):
        self.gets.append(path)
        return {"jobPostingInfo": {"jobReqId": path.rsplit("_", 1)[1], "title": path}}


def test_listing_without_external_path_is_skipped(capsys):
    # A real listing page (2026-10-12), trimmed to 3 entries: REQ-10122974 is
    # listed with only its requisition id, also when searched for by id.
    company = CompanyConfig(name="ing", source="workday",
                            workday_host="ing.wd3.myworkdayjobs.com", workday_site="ICSGBLCOR")
    adapter = ListingFixture(company, load_fixture("workday_ing_listing.json"))
    assert [j.source_id for j in adapter.fetch()] == ["REQ-10122547-1", "REQ-10123091"]
    assert len(adapter.gets) == 2
    assert ("ing: skipped listing entry without externalPath: REQ-10122974"
            in capsys.readouterr().err)


def test_stub_in_a_family_needs_no_plain_listing(capsys):
    jobs = {**_jobs(2, "tech"), "stub": ("REQ-stub", "tech")}
    adapter = FakeWorkday(ING, jobs, {"tech": "Tech"})
    assert {j.source_id for j in adapter.fetch()} == {"REQ-tech-0", "REQ-tech-1"}
    assert [b["appliedFacets"] for b in adapter.posts] == [{}, {"jobFamilyGroup": ["tech"]}]
    err = capsys.readouterr().err
    assert err.count("REQ-stub") == 1
    assert "skipped listing (jobFamilyGroup 'Tech') entry without externalPath: REQ-stub" in err


def test_listing_errors_name_the_step_and_page():
    adapter = FakeWorkday(ING, _jobs(25, "tech"), {"tech": "Tech"})
    real_post = adapter._post

    def failing(path, body):
        if body["offset"] == 20:
            raise KeyError("total")
        return real_post(path, body)

    adapter._post = failing
    with pytest.raises(RuntimeError, match=r"^listing \(jobFamilyGroup 'Tech'\) page at "
                                           r"offset 20: KeyError: 'total'$"):
        adapter.fetch()


def test_category_facet_errors_name_the_step():
    adapter = FakeWorkday(ING, _jobs(1, "tech"), {"tech": "Tech"})
    real_post = adapter._post
    adapter._post = lambda path, body: {**real_post(path, body), "facets": [
        {"facetParameter": "jobFamilyGroup", "values": [{"id": "tech"}]}]}
    with pytest.raises(RuntimeError, match="^category facet jobFamilyGroup: KeyError: 'descriptor'$"):
        adapter.fetch()


def test_detail_errors_name_the_job():
    adapter = FakeWorkday(ING, _jobs(1, "tech"), {"tech": "Tech"})
    adapter._get = lambda path: {"jobPostingInfo": {"title": "no req id"}}
    with pytest.raises(RuntimeError, match="^detail /job/tech-0: KeyError: 'jobReqId'$"):
        adapter.fetch()
