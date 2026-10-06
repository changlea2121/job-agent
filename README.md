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

## Storage

The table `jobs` has primary key `(source, company, source_id)`. Recency uses
`first_published`, which comes from the source. `updated_at` is not used.
`first_seen_at` is the UTC time when this tool first stored the job.

## Tests

```bash
pytest
```

The tests use saved JSON fixtures in `tests/fixtures/` and make no network
calls.
