# job-agent

The discovery layer of a job-search agent. It pulls open roles from company job
boards, maps them to a single `Job` shape, and stores them in SQLite. Each run
records only jobs it hasn't seen before and reports how many were new.

The only supported source is Greenhouse. Companies are listed in
`companies.yaml`.

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

Example output:

```
adyen: 229 fetched, 229 new
nebius: 361 fetched, 361 new
total: 590 fetched, 590 new
```

List jobs first seen in the most recent `fetch` that pass the location filter:

```bash
python -m job_agent new
python -m job_agent new --since 2026-10-01   # everything first seen since then
```

`--since` takes an ISO date or datetime (naive values are UTC). Use it when a
second `fetch`, or one where every company failed, would hide earlier results.
Output is tab-separated: company, title, location, category, url. Jobs whose
location is only "Netherlands" (or a remote variant) are listed last and
marked `[location unclear]`.

## Configuration

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
```

Set `category_from: departments` or `category_metadata_field: <name>` to choose
where the category comes from. If neither is set, `category` is empty.

`location_filter` (see `companies.yaml`) is applied only by `new`; every job
is stored. Keywords are case-insensitive whole words, checked against each
`;`-separated part of a location. `match` keywords show the job; a part that
is only an `unclear` keyword plus "Remote"/"Hybrid" shows it as unclear.
"Eindhoven, Netherlands" and "Remote - Europe" are excluded. Without a
`location_filter` section, `new` shows all new jobs.

## Storage

The table `jobs` has primary key `(source, company, source_id)`. Recency uses
`first_published`, which comes from the source. `updated_at` is not used.
`first_seen_at` is the UTC time when this tool first stored the job. The
table `runs` records when each `fetch` started.

## Tests

```bash
pytest
```

The tests use saved JSON fixtures in `tests/fixtures/` and make no network
calls.
