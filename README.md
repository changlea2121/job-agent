# job-agent

A job-search agent for one person's search: entry-level backend, platform,
infrastructure and ML/AI engineering roles around Amsterdam and the Randstad.

**The problem.** Company career sites list hundreds of roles each, mostly in
other countries, other functions or at senior level, and many of the Dutch
ones are posted in Dutch. Reading them all by hand doesn't scale. Applying
automatically is worse, because a wrong or exaggerated application can't be
taken back. job-agent automates the cheap, reversible steps and keeps a human
in charge of the rest.

## Pipeline

1. **Discover** *(built)*: fetch postings from each company's applicant
   tracking system into SQLite, through one adapter per source type.
2. **Filter** *(built)*: rule-based exclusions applied at output time
   (location, category, seniority, title, years of experience, internship
   direction), so changing a rule never needs a refetch.
3. **Label** *(built)*: an interactive `review` loop builds an evaluation set
   (`yes` / `maybe` / `no` with reasons), which is also used to check every
   new rule before it is enabled.
4. **Score** *(planned)*: rank the jobs that pass the rules.
5. **Tailor** *(planned)*: draft application material for a chosen job.
6. **Submit** *(planned)*: only after explicit human approval, never
   automatically ([decision 1](docs/decisions.md#1-pipeline-with-human-approval-before-submission)).

## Current results

As of 2026-10-11:

| | |
|---|---|
| Companies | 4 (Adyen, Nebius, ING, KPN), on 3 source types |
| Stored jobs | 1,446 (ING 750, Nebius 397, Adyen 256, KPN 43) |
| Shown after the filters | 21 jobs and 4 internships |
| Excluded, by first rule | location 1,180 · category 100 · seniority 99 · experience 20 · internship 15 · title 7 |
| Labels | 65 (7 yes, 1 maybe, 57 no) |

## Design highlights

- **Adapters behind one `Job` schema, with network and parsing split.**
  Each source maps its postings to the same dataclass, and `parse` is a pure
  function tested against real responses saved as fixtures, with no network
  in tests ([decisions 3](docs/decisions.md#3-adapter-pattern-with-a-unified-job-schema),
  [4](docs/decisions.md#4-separate-fetch-and-parse-tests-use-saved-fixtures)).
- **Insert-only storage, filters at output time.** Every posting is stored
  once and never updated; filters run when jobs are listed, so a rule change
  takes effect immediately and can be compared against everything stored
  ([decisions 8](docs/decisions.md#8-insert-only-storage),
  [11](docs/decisions.md#11-filter-at-output-time-never-at-insert-time)).
- **Rules gated by labels.** A rule is enabled only after it is evaluated
  against the labels: how many `no` jobs it catches, and that it excludes no
  `yes` or `maybe` job. Rules that pass that check but rest on too little
  evidence are rejected, and the rejection is recorded
  ([decisions 22](docs/decisions.md#22-exclude-jobs-that-require-3-years-of-experience),
  [27](docs/decisions.md#27-exclude-internships-that-dont-target-cs-data-or-ai-students-exclude-architect-and-service-desk-titles),
  [28](docs/decisions.md#28-experience-ranges-block-by-their-midpoint),
  [29](docs/decisions.md#29-not-excluding-ing-risk-management-trainee-jfg-or-kpn-security-network-engineering-it-management-and-stages)).
- **Polite use of unofficial endpoints.** Where no public API exists, the
  adapter says so, identifies itself, backs off on errors and only downloads
  details for jobs it hasn't stored yet
  ([decisions 23](docs/decisions.md#23-ing-through-workdays-unofficial-json-api)–[25](docs/decisions.md#25-detail-requests-only-for-jobs-not-stored-yet)).

All design decisions, with their context, alternatives and consequences, are
in [docs/decisions.md](docs/decisions.md). Labelling guidelines are in
[docs/labeling.md](docs/labeling.md).

## Data sources

| Source type | Companies | Endpoint | Official? |
|---|---|---|---|
| `greenhouse` | Adyen, Nebius | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`: every job with its full description in one request | Yes, Greenhouse's public job board API ([decision 2](docs/decisions.md#2-public-ats-apis-instead-of-scraping-job-sites)) |
| `workday` | ING | `/wday/cxs/{tenant}/{site}/jobs` (listings, 20 per page) and `/job/{path}` (one detail per job); categories from the `jobFamilyGroup` facet | **No.** The undocumented API Workday's own front end uses; it may change or block without notice ([decision 23](docs/decisions.md#23-ing-through-workdays-unofficial-json-api)) |
| `kpn` | KPN | The careers site's RSS feed (descriptions, category) joined with its JSON API (location, date, ATS id) on the site id | **No.** Both belong to the site's recruitment-marketing platform and are undocumented ([decision 24](docs/decisions.md#24-kpn-through-its-careers-sites-rss-feed-and-json-api)) |

Politeness measures for the unofficial endpoints (`job_agent/sources/http.py`):

- A descriptive User-Agent naming the project and linking to this repository.
- Up to 3 retries on HTTP 429, 5xx and network errors, with exponential
  backoff (1, 2, 4 s) or the server's `Retry-After`, capped at 60 s.
- Workday: at most 4 requests in parallel (category listings, then details),
  and details only for jobs not already in `jobs.db`. The full listing is
  still read every run, so the first run makes about 800 requests and later
  ones about 50 plus one per new job, about 6 s for ING
  ([decisions 25](docs/decisions.md#25-detail-requests-only-for-jobs-not-stored-yet)
  and [32](docs/decisions.md#32-workday-category-listings-in-parallel-no-fetch-time-country-scoping)).
  A detail that still fails is skipped with a warning and fetched on the next
  run.
- KPN: two requests per run.

A fetch error for one company is reported and doesn't stop the others.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Usage

Fetch every configured company into `jobs.db`:

```bash
python -m job_agent fetch
```

Options: `--config PATH` (default `companies.yaml`), `--db PATH` (default
`jobs.db`), `--timeout SECONDS` (default 30).

Example output (a later run):

```
adyen: 237 fetched, 0 new
nebius: 376 fetched, 0 new
ing: 2 fetched, 2 new
ing: new category: Sustainability (1 job)
kpn: 43 fetched, 0 new
total: 658 fetched, 2 new
```

A `new category` line names a category that no stored job of that company
has had (compared case-insensitively, like `exclude_categories`), with how
many fetched jobs carry it, and `, excluded` if `exclude_categories` already
hides it. It is the moment to decide whether to exclude it, before its jobs
reach `review`. A company's first fetch reports every category it has
([decision 31](docs/decisions.md#31-fetch-reports-categories-seen-for-the-first-time)).

For Greenhouse and KPN, "fetched" is the whole board. **For Workday it counts
only the jobs whose details were downloaded**, i.e. those not stored yet, so
after the first run it is close to the number of new jobs rather than the
board size.

List jobs first seen in the most recent `fetch` that pass the filters:

```bash
python -m job_agent new
python -m job_agent new --since 2026-10-01   # everything first seen since then
python -m job_agent new --show-excluded      # also list excluded jobs and why
```

`--since` takes an ISO date or datetime (naive values are UTC). Use it when a
second `fetch`, or one where every company failed, would hide earlier results.
Output is tab-separated: job ref (`company:id`, used by `label`), company,
title, location, category, url. Jobs whose
location is only "Netherlands" (or a remote variant) are listed after the
others and marked `[location unclear]`. Internships follow under
`# internships`, and with `--show-excluded`, excluded jobs follow under
`# excluded` with an extra last column giving the reason (e.g. `seniority: staff`,
`experience: 2-5 years`, `internship: no CS/data/AI keyword`).
The last line counts how many jobs each rule excluded.

## Labelling

Labels (`yes` / `maybe` / `no`, with reasons) build an evaluation set for
relevance scoring. How to choose labels and reasons is described in
[docs/labeling.md](docs/labeling.md). Step through unlabelled jobs that pass
the filters:

```bash
python -m job_agent review                         # all stored jobs
python -m job_agent review --since 2026-10-01
python -m job_agent review --excluded              # jobs the filters removed
python -m job_agent review --excluded --rule seniority --rule category
```

Each job shows its title, company, location, category and url, then the
description lines containing a `preview_keywords` word (years, experience,
Dutch, jaar, ervaring, ...), then, if fewer than 3 lines matched, the start of
the description. Lines containing one of the company's `boilerplate` phrases
are left out of both. Keys: `y` / `m` / `n`, `d` for the full description, `s`
to skip (it comes back next time), `q` to quit. After `m` or `n`, enter reason
numbers such as `1 3` (`no` needs at least one). Choosing `other` asks for a
short note. Every label is saved immediately. `--excluded` lists exclusions by
category, seniority, title, experience and internship before location ones,
and its summary counts excluded jobs you labelled yes or maybe: possible false
exclusions.

Label one job directly, using the ref from `new`:

```bash
python -m job_agent label adyen:8255817 yes
python -m job_agent label adyen:8255817 no --reason dutch_required --reason too_senior
python -m job_agent label adyen:8255817 no --reason other --note "starts in 2027"
```

Summarize the labels file (counts per label, reason, company, and by the
filter decision at labelling time):

```bash
python -m job_agent stats
```

Relabelling a job replaces its label. If a ref matches jobs from more than one
source, use `source:company:id`.

Labels are stored in `labels.jsonl` (change with `--labels PATH`, so each
person can keep their own file), one JSON object per job, keyed by
`(source, company, source_id)`. Each label holds a snapshot of the job (title,
location, category, url, full description) and the filter decision at the
time (`kept`, or `excluded` with the rule), so the file stays usable after
postings close or `jobs.db` is rebuilt.

**`labels*.jsonl` is gitignored and must be backed up separately** (for
example in a synced folder or a private repository). It holds personal
judgments, and it is the only data here that cannot be fetched again.

## Configuration

Each company names its source type and that source's fields:

```yaml
companies:
  - name: adyen
    source: greenhouse
    board_token: adyen                     # boards-api.greenhouse.io/v1/boards/{token}/jobs
    category_from: departments             # category = Greenhouse department name(s)

  - name: nebius
    source: greenhouse
    board_token: nebius
    category_metadata_field: Job Category  # category = this metadata entry's value

  - name: ing
    source: workday
    workday_host: ing.wd3.myworkdayjobs.com  # tenant = first label ("ing")
    workday_site: ICSGBLCOR                  # careers site, from the apply links
    category_from: job_family_group          # category = Workday "Job Category" facet
    workday_max_stub_share: 0.10             # optional; see below

  - name: kpn
    source: kpn
    base_url: https://jobs.kpn.com
    category_from: expertise                 # category = the RSS feed's category
```

| `source` | Required fields | `category_from` options |
|---|---|---|
| `greenhouse` | `board_token` | `departments`, or `metadata` with `category_metadata_field: <name>` (set the field alone to imply `metadata`) |
| `workday` | `workday_host`, `workday_site` | `job_family_group` |
| `kpn` | `base_url` | `expertise` |

Without `category_from`, `category` is empty. Missing fields or a
`category_from` the source doesn't support fail at load time, naming the
company.

How each source fills the `Job` fields:

- **Greenhouse:** `source_id` is the job id, `first_published` the source's
  `first_published`.
- **Workday:** `source_id` is the requisition id (`REQ-…`), so a reposted
  requisition isn't counted as new. `location` is the office plus country,
  then any additional locations: "CDR (Amsterdam - Cedar), Netherlands".
  `first_published` is the posting's `startDate` at midnight Europe/Amsterdam.
  Listings with only a requisition id and no `externalPath` (a few at a time)
  are skipped with a warning naming the id. If more than
  `workday_max_stub_share` of all listed entries (default 0.10) are like that,
  the API format has probably changed and the company fails instead
  ([decision 30](docs/decisions.md#30-workday-listings-without-externalpath-are-skipped-errors-name-the-step)).
- **KPN:** `source_id` is the ATS vacancy id (`external_id`); whether it stays
  stable across re-imports is still being checked
  ([decision 24](docs/decisions.md#24-kpn-through-its-careers-sites-rss-feed-and-json-api)).
  `location` is "city, Nederland", `first_published` the API's `created`.

### Filters

The filters below are applied only by `new` and `review`, in this order; every
job is stored, and each excluded job is counted under the first rule that
removed it.

1. `location_filter`: case-insensitive whole words, checked against each
   `;`-separated part of a location. `match` keywords show the job; a part
   that is only an `unclear` keyword plus "Remote"/"Hybrid" shows it as
   unclear. "Eindhoven, Netherlands" and "Remote - Europe" are excluded.
   Without a `location_filter` section, no job is excluded by location.
2. `exclude_categories` (per company): categories to hide, exact match,
   case-insensitive. Jobs without a category are kept.
3. `title_filter.exclude_seniority` (`seniority`): case-insensitive whole
   words, English and Dutch ("sr" matches "Sr." but not "SRE"; "hoofd" doesn't
   match "Hoofddorp"). Phrases in `title_filter.exceptions`, such as "member
   of technical staff", are ignored when matching.
4. `title_filter.exclude_titles` (`title`): roles excluded whatever their
   seniority, internships included, such as "business analyst", "technician",
   "architect" or "servicedesk" (case-insensitive whole words). Data analyst
   and data scientist are deliberately not listed: whether they fit depends on
   the work.
5. `experience_filter.min_years` (`experience`, default 3): excludes jobs whose
   description requires at least that many years ("5+ years", "at least 3
   years", "minimaal 3 jaar werkervaring"). **A range blocks when its midpoint
   is above the threshold:** with 3, "2-5 years" and "3-5 years" block, "1-3"
   and "2-4" pass. Years in a nice-to-have section or softened in their clause
   ("ideally 4+ years", "is a plus") are ignored, as are years that a degree
   other than a PhD can replace ("3+ years or an MSc"). Without the section,
   the rule is off.
6. `internship_filter.require_description` (`internship`): applies to
   internships only (see below). An internship is excluded when its
   description names none of these keywords (computer science, informatica,
   software, machine learning, data science, engineering, ...), i.e. when it
   doesn't target CS, data or AI students. Without the section, the rule is
   off.

Of the jobs left, titles containing a `title_filter.internship` keyword
(intern, graduate, werkstudent, stagiair, meewerkstage, ...) are listed as
internships. `title_filter.internship_dutch` keywords ("stage") count when the
title also has a Dutch cue such as "(m/v)" or "bij", **or when the keyword is
the first word of the title** ("Stage ING Private Banking"), since elsewhere in
English "stage" usually means a phase ("Early-Stage").

`label_reasons` maps each reason allowed in labels to a short description,
which `review` shows next to the reason number. Names use lowercase letters,
digits and `_`. Without this section, `label` and `review` refuse to run.
`preview_keywords` lists the words (case-insensitive, whole words) whose
description lines `review` shows first. Per company, `boilerplate` lists
phrases (case-insensitive substrings) marking lines the preview leaves out,
such as a standard company intro or benefits list.

## Storage

The table `jobs` has primary key `(source, company, source_id)`. Recency uses
`first_published`, which comes from the source. `updated_at` is not used.
`first_seen_at` is the UTC time when this tool first stored the job. The
table `runs` records when each `fetch` started.

## Tests

```bash
pytest
```

The tests use saved JSON and RSS fixtures in `tests/fixtures/` (real responses,
trimmed to a few jobs, with personal contact details replaced) and make no
network calls.
