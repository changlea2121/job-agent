# job-agent

The discovery layer of a job-search agent. It pulls open roles from company job
boards, maps them to a single `Job` shape, and stores them in SQLite. Each run
records only jobs it hasn't seen before and reports how many were new.

The only supported source is Greenhouse. Companies are listed in
`companies.yaml`.

Design decisions, with their context and alternatives, are recorded in
[docs/decisions.md](docs/decisions.md).

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
`# excluded` with an extra last column giving the reason (e.g. `seniority: staff`).
The last line counts how many jobs each rule excluded.

## Labelling

Labels (`yes` / `maybe` / `no`, with reasons) build an evaluation set for
relevance scoring. Step through unlabelled jobs that pass the filters:

```bash
python -m job_agent review                         # all stored jobs
python -m job_agent review --since 2026-10-01
python -m job_agent review --excluded              # jobs the filters removed
python -m job_agent review --excluded --rule seniority --rule category
```

Each job shows its title, company, location, category and url, then the
description lines containing a `preview_keywords` word (years, experience,
Dutch, ...), then, if fewer than 3 lines matched, the start of the
description. Lines containing one of the company's `boilerplate` phrases are
left out of both. Keys: `y` / `m` / `n`, `d` for the full description, `s` to
skip (it comes back next time), `q` to quit. After `m` or `n`, enter reason
numbers such as `1 3` (`no` needs at least one). Choosing `other` asks for a
short note. Every label is saved immediately. `--excluded` lists category and
seniority exclusions before location ones, and its summary counts excluded
jobs you labelled yes or maybe: possible false exclusions.

Label one job directly, using the ref from `new`:

```bash
python -m job_agent label adyen:8255817 yes
python -m job_agent label adyen:8255817 no --reason dutch_required --reason too_senior
python -m job_agent label adyen:8255817 no --reason other --note "starts in 2027"
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

The filters below are applied only by `new`, in this order; every job is
stored, and each excluded job is counted under the first rule that removed it.

- `location_filter`: case-insensitive whole words, checked against each
  `;`-separated part of a location. `match` keywords show the job; a part
  that is only an `unclear` keyword plus "Remote"/"Hybrid" shows it as
  unclear. "Eindhoven, Netherlands" and "Remote - Europe" are excluded.
  Without a `location_filter` section, no job is excluded by location.
- `exclude_categories` (per company): categories to hide, exact match,
  case-insensitive. Jobs without a category are kept.
- `title_filter.exclude_seniority`: case-insensitive whole words ("sr"
  matches "Sr." but not "SRE"). Phrases in `title_filter.exceptions`, such as
  "member of technical staff", are ignored when matching.
- `title_filter.exclude_titles`: roles excluded whatever their seniority,
  internships included, such as "business analyst" (case-insensitive whole
  words). Counted as the `title` rule. Data analyst and data scientist are
  deliberately not listed: whether they fit depends on the work.

Of the jobs left, titles containing a `title_filter.internship` keyword
(intern, graduate, werkstudent, ...) are listed as internships.
`title_filter.internship_dutch` keywords ("stage") count only next to a Dutch
cue such as "(m/v)" or "bij", since in English "stage" usually means a phase
("Early-Stage").

`label_reasons` maps each reason allowed in labels to a short description,
which `review` shows next to the reason number. Names use lowercase letters,
digits and `_`. Without this section, `label` and `review` refuse to run.
`preview_keywords` lists the words (case-insensitive, whole words) whose
description lines `review` shows first. Per company, `boilerplate` lists
phrases (case-insensitive substrings) marking lines the preview leaves out,
such as a standard company intro.

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
