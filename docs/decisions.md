# Design decisions

This file records the main design decisions in job-agent: the context, what was chosen, what else was considered, and what it costs. It follows a lightweight ADR (Architecture Decision Record) format. New decisions are appended at the end; superseded ones are marked, not deleted.

---

## 1. Pipeline with human approval before submission

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** Fully automated job agents can search, tailor CVs and submit applications without review. Automatically tailored CVs can contain inaccurate or exaggerated claims, and a submitted application cannot be taken back.

**Decision.** The project is split into four stages: discover, filter, tailor, submit. Discovery and filtering can be fully automated. Tailoring produces drafts only. Submission always requires explicit human approval and never happens automatically.

**Alternatives.** End-to-end automation including submission.

**Consequences.** Less throughput than mass auto-applying, but every application is reviewed. Risk is lowest at the discovery stage (a missed or extra job costs little) and highest at submission, so automation is applied in that order.

---

## 2. Public ATS APIs instead of scraping job sites

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** Job postings can be collected by scraping aggregators such as LinkedIn or by reading the companies' own applicant tracking systems. Scraping LinkedIn violates its terms of service, risks account bans, and breaks whenever the HTML changes.

**Decision.** Read postings from the public job board APIs of each company's ATS. Greenhouse (used by Adyen and Nebius) exposes `boards-api.greenhouse.io/v1/boards/{token}/jobs` without authentication. The ATS behind each company is identified by inspecting its careers page in browser DevTools.

**Alternatives.** Scraping LinkedIn or other aggregators; parsing each company's careers page HTML.

**Consequences.** Structured, stable data with no login. Coverage is limited to companies whose ATS is supported, so each new ATS (for example Workday, used by ING) needs its own adapter. Companies with a self-built careers page would still need HTML parsing.

---

## 3. Adapter pattern with a unified Job schema

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** The target companies use different ATS platforms with different response formats.

**Decision.** Each ATS gets one adapter in `job_agent/sources/`, registered by name. Every adapter maps its postings to the same `Job` dataclass (source, company, source_id, title, location, url, description, category, first_published). Everything downstream (storage, filtering, output) only depends on `Job`. Per-company settings live in `companies.yaml`.

**Alternatives.** Company-specific scripts; handling format differences throughout the codebase.

**Consequences.** Adding a company on an already supported ATS is a one-line config change. Adding a new ATS means one new adapter file plus a registry entry, with no changes downstream.

---

## 4. Separate fetch and parse; tests use saved fixtures

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** Tests that call live APIs are slow, flaky, and change results whenever postings change.

**Decision.** Each adapter has `fetch()`, which makes the HTTP call (with a timeout), and `parse(payload)`, a pure function. Tests only call `parse()` on fixtures captured from real responses and trimmed to a few jobs. Edge cases not present in live data are added as clearly marked hand-edited or made-up inputs.

**Alternatives.** Live integration tests; mocking the HTTP layer.

**Consequences.** Tests are fast and deterministic. Fixtures can drift from the live format over time, so they should be refreshed occasionally from real responses.

---

## 5. `first_published` for recency, not `updated_at`

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** The live Nebius board returned the same `updated_at` timestamp for many unrelated jobs, which indicates bulk updates on the company side. `updated_at` therefore says nothing about when a job appeared.

**Decision.** Use `first_published` (the source's publication time) for recency and ignore `updated_at`.

**Alternatives.** Using `updated_at`, which would make old postings look new after every bulk edit.

**Consequences.** Recency reflects when the company actually published the job.

---

## 6. Deduplication key and counting new jobs

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** Every fetch returns all open jobs, most of which were seen before. IDs are only unique within one ATS.

**Decision.** The `jobs` table uses the primary key `(source, company, source_id)` and rows are written with `INSERT OR IGNORE`, so the database enforces deduplication. The number of new jobs is the difference in `total_changes` before and after the batch insert. SQLite's `changes()` was rejected because it only reflects the last statement, which undercounts with batch inserts. A test runs the same fixture twice and checks that the second run reports zero new jobs.

**Alternatives.** Deduplicating in Python by comparing against existing IDs; counting with `changes()`.

**Consequences.** Deduplication and counting are correct by construction and covered by tests.

---

## 7. `first_seen_at` alongside `first_published`

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** "Published by the company" and "new to me since the last run" are different questions.

**Decision.** Store `first_seen_at` (UTC, set once at insert, never overwritten). `first_published` is used for sorting and judging a job's age; `first_seen_at` answers "what is new since the last run".

**Consequences.** Daily output depends only on what this tool has seen, regardless of how the company dates its postings.

---

## 8. Insert-only storage

**Date:** 2026-10-06 · **Status:** Accepted (expected to be revisited)

**Context.** The simplest correct storage for "detect new jobs" only needs inserts.

**Decision.** Existing rows are never updated.

**Alternatives.** Upsert (update existing rows, insert new ones), with explicit rules about which fields may change.

**Consequences.** `first_seen_at` can never be overwritten. On the other hand, edits to a posting (title, description) are not picked up, closed jobs stay in the database, and a change to how a field is derived (for example the category source) only applies to existing rows after a database rebuild. This becomes more important once descriptions are used for relevance scoring. The likely next step is upsert for descriptive fields plus a `last_seen_at` column, which would also allow detecting closed postings.

---

## 9. Per-company category source

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** Greenhouse has standard fields (such as `departments`) and company-defined custom fields (`metadata`). Nebius puts its job category in a custom metadata field called "Job Category"; Adyen has no metadata but fills in `departments`.

**Decision.** Each company configures where its category comes from: `category_metadata_field: <name>` or `category_from: departments`. Multiple values are joined with ", ". With neither set, category is `None`.

**Alternatives.** Hardcoding one source for all companies.

**Consequences.** New companies only need a config entry. Category names are not comparable across companies (Adyen "People" vs Nebius "HR"), so anything that uses categories must be configured per company.

---

## 10. Fail-fast config validation

**Date:** 2026-10-06 · **Status:** Accepted

**Context.** A typo in `companies.yaml` should not surface halfway through a fetch.

**Decision.** The whole config is validated when it is loaded. Invalid values raise `ValueError` with the company name before any network call.

**Consequences.** Config mistakes are caught immediately. If one company fails at runtime (for example a network error), the others still run and the command exits with code 1.

---

## 11. Filter at output time, never at insert time

**Date:** 2026-10-07 · **Status:** Accepted

**Context.** Because storage is insert-only (decision 8), anything decided at insert time is effectively permanent. Changing the category source already required one database rebuild.

**Decision.** `fetch` stores every job worldwide. Location and rule-based filters are applied only when results are printed.

**Alternatives.** Filtering at insert time for a smaller database.

**Consequences.** The database holds many irrelevant jobs, but changing or widening a filter never requires a rebuild and never loses data.

---

## 12. Location matching for the Randstad

**Date:** 2026-10-07 · **Status:** Accepted

**Context.** The target area is the Randstad. Real location fields can list several places separated by `;`, mix cities and countries, and sometimes name only "Netherlands". City names have variants (The Hague, Den Haag, 's-Gravenhage).

**Decision.** Keywords live in `companies.yaml`. A location field is split on `;` and each part is classified, case-insensitively and with whole-word matching:

- **match:** the part contains a Randstad city keyword;
- **unclear:** the part is only "Netherlands" plus words like "Remote" or "Hybrid";
- **excluded:** anything else, including a specific non-Randstad Dutch city such as Eindhoven.

A job takes the best result of its parts (match > unclear > excluded). Unclear jobs are shown with a `[location unclear]` tag. "Remote - Europe" is excluded.

**Alternatives.** Substring matching (would match "haarlem" inside "Haarlemmerliede"); dropping jobs that only say "Netherlands" (could miss Randstad jobs).

**Consequences.** Biased toward not missing relevant jobs, at the cost of a few unclear ones to check by hand.

---

## 13. "New" means the most recent fetch, with `--since` as an escape hatch

**Date:** 2026-10-07 · **Status:** Accepted

**Context.** "New since the previous run" needs a definition.

**Decision.** Each fetch records a run before fetching. `python -m job_agent new` lists jobs first seen in the most recent fetch. `--since <date or datetime>` lists everything first seen since that time instead.

**Alternatives.** Remembering when `new` was last viewed.

**Consequences.** The default is simple and repeatable. Without `--since`, a second fetch on the same day or a fetch where every company fails would hide earlier results; `--since` covers those cases and multi-day catch-up.

---

## 14. Rule-based filtering with exclusion lists

**Date:** 2026-10-07 · **Status:** Accepted

**Context.** Target roles are backend / platform / infrastructure, ML / AI / data science, and data engineering / analytics, at entry level, with internships shown separately. Category and title conventions differ per company. A first draft of the seniority rule would have removed 411 of 598 stored jobs, which was caught by checking the rule against real data before implementing it.

**Decision.**

- Use exclusion lists, not inclusion lists. Anything not excluded is kept, because inclusion lists miss unexpected title wordings.
- Seniority keywords (in config) are matched against titles: senior, sr, staff, lead, leader, principal, manager, director, head of, vp, vice president, chief. "Manager" is kept because titles containing it are almost never target roles. The phrase "member of technical staff" is exempt.
- Category exclusions are configured per company. Category names can mislead: Nebius "Product" contains data roles, so it is kept. Uncertain categories (Adyen Professional Services, Support) are kept until real output shows otherwise. Nebius "Hardware Infrastructure" was first excluded but restored after `--show-excluded` revealed software and SRE roles in Amsterdam under it (including an Early Talent SRE role); its manager and senior titles are still removed by the seniority rule.
- Internships are grouped into their own section rather than excluded. The internship keywords live in config next to the seniority keywords. Dutch "stage" counts only with a Dutch cue in the title, to avoid English phrases like "early-stage".
- The summary shows how many jobs each rule excluded, and `--show-excluded` lists excluded jobs with the reason, so false exclusions can be reviewed.

**Consequences.** Some irrelevant jobs remain in the output. Rules are checkable and adjustable without code changes.

---

## 15. Relevance scoring does not need training data, but evaluation does

**Date:** 2026-10-07 · **Status:** Superseded by [17](#17-labels-for-the-evaluation-set-stored-outside-jobsdb)

**Context.** BM25, embeddings and LLM judgments can score jobs against a CV with no training data (zero-shot). Knowing whether the scores are any good, and choosing thresholds and weights, requires labelled examples.

**Decision.** Add a labelling command next (`label <id> yes/no`), and label a sample of the stored jobs to build an evaluation set before building relevance scoring.

**Consequences.** Scoring can be evaluated with real metrics instead of intuition from the start.

---

## 16. Build one stage at a time; no scheduling until there is a notification channel

**Date:** 2026-10-07 · **Status:** Accepted

**Context.** A scheduled run whose output goes only to a terminal is not seen by anyone. Cron inside WSL only runs while WSL is running.

**Decision.** Run `fetch` and `new` manually for now. Scheduling comes together with a notification channel. The likely setup is GitHub Actions (runs when the laptop is off) with Telegram notifications (free and simple), which will need a way to persist `jobs.db` between runs and to keep tokens in GitHub Secrets.

**Alternatives.** Cron in WSL; WhatsApp or SMS notifications (need a business API or a paid service).

**Consequences.** Each stage is finished and usable before the next starts, which also keeps the project's scope under control.

---

## 17. Labels for the evaluation set, stored outside `jobs.db`

**Date:** 2026-10-07 · **Status:** Accepted; the preview part is superseded by [19](#19-review-preview-skips-per-company-boilerplate)

**Context.** Decision 15 calls for labelled jobs before building relevance scoring. A plain yes/no loses information: "maybe" cases and *why* a job is wrong (Dutch required, too senior) are what scoring needs to get right. Postings disappear from the API once closed, and `jobs.db` is occasionally rebuilt (decision 8), so labels must not depend on either. The rule-based filters (decision 14) also need spot-checking for false exclusions, which is the same kind of judgment.

**Decision.**

- Labels are `yes`, `maybe` or `no`, with reasons from a fixed list in `companies.yaml` (`label_reasons`, name → description), validated at config load. `no` needs at least one reason, `maybe` may have some, `yes` none. The reason `other` requires a short note. No general note field exists, so free text stays the exception.
- Labels live in a JSON Lines file (default `labels.jsonl`, set with `--labels` so each user can keep their own), keyed by `(source, company, source_id)`. One line per job. Relabelling replaces the line. Every save rewrites the file sorted by key, through a temp file and `os.replace`, so a crash cannot leave a half-written file. Loading fails fast, with the line number, on malformed lines or reasons no longer in the config.
- Each label stores a snapshot of the job (title, location, category, url, full description) and the filter decision at labelling time (`kept`, or `excluded` with the rule and detail). The snapshot makes the evaluation set self-contained. The filter decision makes false exclusions (`excluded` + yes/maybe) and false keeps (`kept` + no) directly countable, even after the rules change.
- `new` prints a job ref (`company:source_id`) as its first column. `label <ref> <yes|maybe|no> [--reason ...] [--note ...]` labels one job. `source:company:source_id` resolves the rare ambiguous ref. A job gone from `jobs.db` can still be relabelled from its snapshot.
- `review` steps through unlabelled jobs that pass the filters (internships included), saving after every label. `review --excluded` steps through excluded jobs instead, category and seniority before location, and `--rule` narrows it to specific rules, since most of the 436 location exclusions are plainly correct. Requirements like Dutch or years of experience usually sit far below a company intro (Adyen's first 600 characters are always the same boilerplate), so the preview first lists the description lines containing a `preview_keywords` word from the config (years, experience, Dutch, Nederlands, degree, required, must; whole words, each line cut at 200 characters), then the start of the description if at least 150 of the 1000 characters are left. `d` shows the full description. The keywords also match some boilerplate ("candidate experience"), which is accepted as the price of not missing requirements.
- `labels*.jsonl` is gitignored. The repository is public, and labels reveal personal information (language skills, experience level through reasons like `dutch_required`), and snapshots are full third-party job descriptions. The file is the only data here that cannot be rebuilt, so it must be backed up separately, e.g. in a synced folder or a private repository.

**Alternatives.** A `labels` table in `jobs.db` (lost on rebuild); an append-only log where the last line wins (keeps history, but grows and needs compaction); storing only the key and re-reading the job from `jobs.db` (breaks once postings close); committing `labels.jsonl` (versioned backup, but publishes personal data in a public repo).

**Consequences.** The evaluation set survives database rebuilds and closed postings. Renaming or removing a reason in the config requires editing the labels file, which keeps old labels consistent with the current list. Backups are a manual responsibility. Each save rewrites the whole file (about 5.5 KB per label), which is fine for hundreds of labels.

---

## 18. Exclude business analysts by title; leave data analyst and data scientist to labelling

**Date:** 2026-10-08 · **Status:** Accepted

**Context.** Some roles never fit the target directions (decision 14), whatever their seniority or category: business analyst is one. Others are ambiguous by title. "Data analyst" and "data scientist" can mean SQL reporting or ML engineering depending on the team, and for internships analysis work is still useful experience.

**Decision.**

- A new `title` rule, `title_filter.exclude_titles` in `companies.yaml` (case-insensitive whole words), excludes jobs whose title contains a listed role. It starts with `business analyst` only. It is checked after `seniority`, so "Senior Business Analyst" counts as seniority. It applies to internships too, because exclusion happens before internship grouping. It is counted in the `new` summary and shown by `--show-excluded` and `review --excluded --rule title`.
- No title rule for data analyst or data scientist. Those are judged per job when labelling, and later by relevance scoring.
- The `wrong_direction` label reason now says what to judge: the actual work is not backend/platform/infra or ML/AI engineering, judged by the description rather than the title. For full-time jobs, analysis-focused DA/DS work counts as wrong direction; for internships it does not.

**Alternatives.** Excluding all analyst and data scientist titles (would drop ML-heavy data science roles and analysis internships); no title rule at all (business analyst roles would keep needing manual rejection).

**Consequences.** One clear-cut role is removed automatically (one job in the current `jobs.db`). The ambiguous ones stay visible, and the labels record how they were judged, which gives relevance scoring examples of the distinction.

---

## 19. Review preview skips per-company boilerplate

**Date:** 2026-10-08 · **Status:** Accepted

**Context.** The preview from decision 17 listed keyword lines and then the start of the description. On real data, both were dominated by company boilerplate. Seven Adyen lines appear in 185–234 of 238 postings ("This is Adyen", the "candidate experience" paragraph, the DEI text), and seventeen Nebius lines appear in all 381. One of them, "Applicants must be authorized to work … required to provide proof", matched "must" and "required" in every Nebius job. The keyword list also missed common wordings ("experienced", "fluent", "bachelor").

**Decision.**

- Each company in `companies.yaml` has a `boilerplate` list of phrases (case-insensitive substrings, validated at load like other per-company config). Lines containing one are left out of both the matching lines and the description start. The initial lists were taken from the lines that repeat across most of each company's postings.
- The description start is shown only when fewer than 3 lines match. Three or more matching lines usually cover the requirements, and the start is mostly intro text.
- `preview_keywords` adds experienced, requirement, requirements, fluent, native, proficiency, bachelor, master, msc and phd.
- The rest of decision 17's preview is unchanged: 1000-character budget, matching lines cut at 200 characters, start only if at least 150 characters are left, and `d` shows the full, unfiltered description.

**Alternatives.** Skipping a fixed number of characters at the start (intros differ in length per company and job); detecting repeated lines automatically from `jobs.db` at review time (no config to maintain, but less predictable, and a company with few postings has no repetition to detect).

**Consequences.** Previews show mostly requirement lines. Boilerplate lists need maintenance when a company changes its template, and a new company starts without one until its repeated lines are added. Generic keywords like "experience" and "master" still match some non-requirement lines.
