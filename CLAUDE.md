# job-agent

A job-search agent built as a four-stage pipeline:

1. **Discover**: fetch postings from company job boards into SQLite. *(implemented)*
2. **Filter**: pick relevant jobs from the stored set.
3. **Tailor**: prepare application materials for a chosen job.
4. **Submit**: apply only after explicit human approval. Never auto-submit.

Build one stage at a time. Don't add code for a later stage until asked.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'   # setup (venv, not system/conda Python)
.venv/bin/pytest                                             # tests
.venv/bin/python -m job_agent fetch                          # run discovery for all companies
.venv/bin/python -m job_agent new                            # jobs from the latest fetch passing the filters
```

## Conventions

- **Adapters + unified schema.** Each source (e.g. Greenhouse) is an adapter in
  `job_agent/sources/`, registered in `ADAPTERS`, and maps raw postings to the
  `Job` dataclass in `models.py`. Source-specific details stay inside the
  adapter. Split `fetch()` (network) from `parse(payload)` (pure) so parsing
  can be tested.
- **Per-company config lives in `companies.yaml`, not code.** For example, the
  category source is `category_from: departments` or
  `category_metadata_field: <name>`.
- **Recency:** use `first_published` from the source, never `updated_at`.
  `first_seen_at` (UTC, set on insert) records when *we* first saw a job and
  answers "new since last run".
- **Storage is insert-only.** Primary key is `(source, company, source_id)`.
  Use `INSERT OR IGNORE`; never update existing rows. Count new rows with the
  `total_changes` delta, not `changes()`.
- **Filter at output time, never at insert time.** Rules are exclusion lists
  in `companies.yaml` (`location_filter`, per-company `exclude_categories`,
  `title_filter`); changing them never needs a DB rebuild. Internships are
  grouped, not excluded. Each `fetch` records a row in `runs`; `new` lists
  jobs with `first_seen_at` >= the latest run (or `--since`).
- **Tests use saved JSON fixtures in `tests/fixtures/`, with no live network.**
  Capture new fixtures from real responses and trim them to a few jobs.
- **Fail fast on config.** Validate config at load time (e.g.
  `CompanyConfig.__post_init__`) and raise `ValueError` with the company name,
  rather than failing mid-fetch. Runtime fetch errors for one company are
  reported and don't stop the others.
- **Record design decisions in `docs/decisions.md`.** When a task adds or
  changes a design decision, append a new numbered entry (Date, Status,
  Context, Decision, Alternatives, Consequences). Never delete or rewrite an
  old entry's decision; mark it "Superseded by N" and link the new one.
