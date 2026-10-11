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

**Outcome (2026-10-08).** The 7 Nebius "Hardware Infrastructure" jobs kept by restoring the category (all in Amsterdam, first seen 2026-10-06) were labelled 2 yes (Site Reliability Engineer in Hardware Infrastructure; SRE - Early Talent), 1 maybe (SRE in Network Infrastructure), and 4 no. Of the 4 no, three Software Engineer roles in Hardware/Network Infrastructure are `experience_required`, and the L3 Support Engineer is `wrong_direction`. Six of the seven were the right direction and three were worth applying to, so restoring the category was correct. Physical-infrastructure titles that arrived later under the same category are handled by title rules (decisions 20 and 21), not by excluding the category.

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

---

## 20. Exclude technicians by title

**Date:** 2026-10-08 · **Status:** Accepted

**Context.** "Technician" appears in 23 stored Nebius titles: data center, IT, field network, cabling, helpdesk and physical security technicians. All of them are physical-infrastructure or IT-support work, which the labelling guidelines ([docs/labeling.md](labeling.md)) count as wrong direction. Most were already excluded by location or seniority, but "Help Desk Technician (Tier 1)" in Amsterdam was shown by `new` and `review`.

**Decision.** Add `technician` to `title_filter.exclude_titles` (the `title` rule from decision 18). Whole-word matching leaves "Technical ..." and "Technology ..." titles alone.

**Alternatives.** Labelling these jobs `no` / `wrong_direction` one by one (they keep reappearing with each new location); excluding the categories they fall under (Nebius "Hardware Infrastructure" also holds software and SRE roles, see decision 14).

**Consequences.** One more job in the current `jobs.db` is excluded, under `title: technician`, and future technician postings never reach the review queue. A software role titled "technician" would be missed. None exists so far, and `review --excluded --rule title` can spot-check for one.

---

## 21. Exclude mechanical and electrical titles

**Date:** 2026-10-08 · **Status:** Accepted

**Context.** After all kept jobs were labelled, the Amsterdam "Electrical Design Engineer (MV/HV)" and "Mechanical Design Engineer" postings were both labelled `no` / `wrong_direction`. `jobs.db` holds 15 titles containing "mechanical" or "electrical", all Nebius data center design or operations roles (mostly under "Hardware Infrastructure", one under "Product"), reposted per location. They are physical infrastructure, which [docs/labeling.md](labeling.md) counts as wrong direction.

**Decision.** Add `mechanical` and `electrical` to `title_filter.exclude_titles` (the `title` rule, decisions 18 and 20). Whole-word matching leaves words such as "electromechanical" alone.

**Alternatives.** Excluding Nebius "Hardware Infrastructure" (would also drop the SRE and software roles that decision 14 restored, see its outcome note); keep labelling these jobs by hand as they reappear per location.

**Consequences.** Data center mechanical and electrical roles never reach the review queue. A software role with one of these words in its title (e.g. "Software Engineer, Electrical Systems Tooling") would be excluded too. None exists so far, and `review --excluded --rule title` can spot-check for one.

---

## 22. Exclude jobs that require 3+ years of experience

**Date:** 2026-10-08 · **Status:** Accepted; the reading of ranges ("Ranges use the lower bound") is superseded by [28](#28-experience-ranges-block-by-their-midpoint)

**Context.** After all kept jobs were labelled, `experience_required` was the most common reason (11 of 20 `no` labels), and every one of those postings states the requirement explicitly ("5+ years", "at least 4 years", "5 or more years"). [docs/labeling.md](labeling.md) defines the blocker as an explicit 3+ years; 1–3 years is not one.

**Decision.**

- `job_agent/experience.py` extracts required years from a description, line by line, and a new `experience` rule (`experience_filter.min_years` in `companies.yaml`, default 3) excludes a job when the highest blocking requirement reaches the threshold. It runs after the title rules and applies to internships too. The detail is e.g. `5+ years`.
- What counts: a number (digits, English or Dutch number words) followed by years/jaar, in a line that mentions experience or says what the years were spent on ("3+ years administering Entra ID"). Ranges use the lower bound ("3-5 years" blocks, "1-3 years" does not). With several numbers, the highest blocking one counts.
- What does not count: years under a nice-to-have heading ("Nice to have:", "It will be an added bonus if you have:"); years softened in their own clause, by a word before them ("ideally 4+ years") or after them ("…is a plus"), so "5+ years, ideally in fintech" still blocks; timeframes and history ("medium-term (1-3 years)", "within 2 years", "20 years of payments data"); and years that a Master's, MSc, Bachelor's or other degree can replace ("3+ years or an MSc"), because I will have an MSc. A PhD-only alternative still blocks. "Or equivalent practical background" still blocks.
- Evaluated before enabling, against `labels.jsonl` (27 labels): it catches 11 of 11 `experience_required` labels and excludes none of the 6 `yes` and 1 `maybe` jobs, or any other `no` job (two of those require 2 years, below the threshold). Across all 619 stored jobs, 434 require 3+ years, 31 fewer, and 154 state none. The 27 labels contain no hard cases, so those were checked against real lines from all stored postings and against made-up inputs (Dutch phrasing and degree alternatives do not occur in the stored postings yet).
- **The evaluation set for relevance scoring should reflect jobs that pass the rules,** since the scorer will only see those. Excluded jobs are sampled from time to time with `review --excluded --rule experience` to check the rule for false exclusions. Those labels are for checking the rules, not for evaluating scoring.

**Alternatives.** Leaving years to labelling and relevance scoring (the most common blocker would keep reaching the review queue); a stricter extractor that only accepts lines containing "experience" (missed real requirements such as "3+ years administering…"); treating every degree alternative as a blocker.

**Consequences.** 9 of the 23 jobs that passed the earlier rules are now excluded, all of them labelled `experience_required`. A requirement phrased in a way the extractor does not know (e.g. "a decade of experience") is missed, so the job stays visible, which errs toward showing too much. A requirement in an unusual nice-to-have wording is treated as hard, so the job is excluded wrongly. The sampling above is how such cases get found.

---

## 23. ING through Workday's unofficial JSON API

**Date:** 2026-10-11 · **Status:** Accepted

**Context.** careers.ing.com is a Radancy (TalentBrew) front end whose apply links go to Workday: tenant `ing` on `ing.wd3.myworkdayjobs.com`, site `ICSGBLCOR` (750 jobs, 49 in the Netherlands). Workday has no documented public job board API like Greenhouse's (decision 2). The only JSON is `/wday/cxs/{tenant}/{site}`, which the Workday front end itself uses. Its listing returns at most 20 jobs per page (larger pages are a 400) and carries no description, date or category; each job's detail has the description, `startDate`, location, additional locations and country. The category ("Job Category") exists only as the `jobFamilyGroup` facet. `ICSNLDGEN`, listed in Workday's robots.txt next to the global site, holds a 5-job subset of the same jobs.

**Decision.**

- A `workday` adapter (`job_agent/sources/workday.py`), configured with `workday_host` and `workday_site`. With `category_from: job_family_group` it runs the listing once per job family group (48 requests for 750 jobs today) to learn each job's category; if those add up to fewer jobs than the total, a plain listing adds the rest without a category.
- `source_id` is `jobReqId` (REQ-…, or a Polish PB_ id), so a requisition reposted under a new posting URL is not a new job. The listing's `bulletFields[0]` equals it (746 of 746 checked), which lets the adapter skip details of stored jobs (decision 25).
- `location` is `"<location>, <country>"` plus the additional locations, joined with `"; "`: "CDR (Amsterdam - Cedar), Netherlands". Office codes carry the city, which the location filter matches; the country is only given for the primary location. `first_published` is `startDate` (a date) at midnight Europe/Amsterdam.
- Politeness, since the API is not meant for us: at most 4 detail requests in parallel, a descriptive User-Agent with the repository URL, and up to 3 retries on 429, 5xx and network errors with exponential backoff (1, 2, 4 s) or the server's `Retry-After`, capped at 60 s (`job_agent/sources/http.py`). A detail that still fails is skipped with a warning; it is still unknown on the next run, so it is fetched then.
- ING's categories are excluded or kept like the other companies' (decision 14): retail, private banking, procurement and other non-engineering groups are excluded; Tech, Data/Modelling & Analytics, Security, Transformation, Risk Management (model developers), Financial Crime & Fraud Prevention, Additional JFG and Trainee JFG are kept.

**Alternatives.** Parsing the Radancy search pages (HTML, 15 per page, and still no category); `ICSNLDGEN` only (misses most Dutch jobs); fetching only Dutch locations by their facet ids (filtering at fetch time, against decision 11).

**Consequences.** The API is undocumented and can change or block us without notice; the adapter then fails for ING only and the other companies still fetch. The first live run made about 800 requests in 2 minutes and still got two 429s after retries (both picked up by the next run); later runs make about 50 listing requests plus one per new job. Old evergreen postings have a `startDate` from as early as 2022.

---

## 24. KPN through its careers site's RSS feed and JSON API

**Date:** 2026-10-11 · **Status:** Accepted

**Context.** jobs.kpn.com is a recruitment-marketing CMS that the ATS pushes vacancies into (its routes have push hooks for Ubeeo, Connexys and OTYS); applications go through the site's own form, so the ATS itself has no public endpoint. Decision 2 expected such companies to need HTML parsing. Two machine-readable endpoints exist, neither documented: the platform's RSS feed (`/feeds/rss`, all 43 jobs with full HTML descriptions, one category, `pubDate` and link, but no location) and the site's own JSON API (`/api/vacancy/?pageSize=999`, location, creation time with time zone and the ATS id, but no description). The API only accepts query parameters with an `X-Requested-With: XMLHttpRequest` header. All 43 descriptions are in Dutch.

**Decision.**

- A `kpn` adapter (`job_agent/sources/kpn.py`), configured with `base_url`, fetches both and joins them on the site id in the RSS link (`/vacature/2041/slug`). Two requests per run, no HTML parsing. An RSS item missing from the API is skipped with a warning (it has no ATS id yet) and comes in on a later run.
- `source_id` is the API's `external_id`, labelled "ATS Vacancy ID" in the site's JSON-LD, rather than the site id, on the assumption that it survives the site re-importing a vacancy (slugs such as `ai-engineer-4` suggest titles get re-posted). **This is unverified.** If duplicate KPN postings appear over the coming weeks, this choice is revisited.
- `location` is `"<city>, <country>"` from the API (`"Amersfoort, Nederland"`), `first_published` the API's `created`, and `category` the RSS category with `category_from: expertise`. Shops, field technicians, customer service, sales, marketing, business support, strategy and project/product management are excluded; Engineering, Network Engineering, IT Management, Security and Stages are kept.

**Alternatives.** Parsing the detail pages' JSON-LD (has the description but an empty address, so the API is still needed, and 43 requests instead of 2); scraping the HTML search results.

**Consequences.** Both endpoints belong to the site's platform and can change with it; the adapter then fails for KPN only. If the platform is used by another company, the adapter could be renamed after the platform and reused with a different `base_url`. Dutch-only postings make the Dutch filter keywords (decision 26) and the `dutch_required` label reason matter more.

---

## 25. Detail requests only for jobs not stored yet

**Date:** 2026-10-11 · **Status:** Accepted

**Context.** The Workday adapter (decision 23) needs one detail request per job. Storage is insert-only (decision 8), so details fetched again for stored jobs are thrown away: about 750 requests per run for ING, where a day brings 10–30 new jobs.

**Decision.** `fetch` passes every adapter `known_ids`, the `source_id`s already stored for that source and company (`JobStore.source_ids`). The Workday adapter still fetches the full listing every run, then requests details only for listings whose requisition id is not known. Greenhouse (one request returns everything) and KPN (two requests) ignore it.

**Alternatives.** Fetching every detail every run (simple, but 750 requests against an unofficial API each time); fetching details only for jobs passing the location filter (filtering at fetch time, against decision 11).

**Consequences.** For ING, `fetch` reports only the jobs whose details it fetched, so "N fetched" is the number of new candidates rather than the board size. Because the full listing is still read every run, a future `last_seen_at` (to tell when a job disappears) remains possible without extra requests. A stored job's later edits are never seen, as with every other source.

---

## 26. Dutch title keywords and three more locations

**Date:** 2026-10-11 · **Status:** Accepted

**Context.** Run against the ING and KPN postings, the title rules missed Dutch internships ("Stagiair …", "Meewerkstage …", "ICT stagiair(e) bij KPN", and "Stage ING Private banking", which has no Dutch cue word) and Dutch senior titles ("Retail Regiodirecteur"). Dutch years phrasing ("Minimaal 3 jaar relevante ervaring", "3-5 jaar ervaring", "Ten minste 5 jaar werkervaring") was already handled by decision 22, with no false positives from the benefits lines ("€ 1500 per jaar"). KPN's tech roles are mostly in Amersfoort (13 of its 43 jobs), which the location filter (decision 12) excluded, as it did Diemen and Hilversum.

**Decision.**

- `title_filter.internship`: add `meewerkstage`, `stagiair` and `stagiaire`. An `internship_dutch` keyword (`stage`) now also counts when it is the first word of the title.
- `title_filter.exclude_seniority`: add `directeur`, `regiodirecteur`, `teamleider` and `hoofd`. No generic "-manager" compound matching: Relatiemanager and Ketenmanager are role names, and their categories are excluded anyway.
- `medior` is not added. It means roughly 2–5 years, 1–3 years is not a blocker for me, and the one medior posting already states 5 years, which the experience rule catches.
- `location_filter.match`: add `diemen`, `amersfoort` and `hilversum`. Recall matters more than precision for now.
- `preview_keywords`: add Dutch words (jaar, ervaring, werkervaring, minimaal, vereist, kennis, opleiding), and per-company `boilerplate` for ING's and KPN's benefits blocks so `jaar` does not surface "€ 1500 per jaar".

**Alternatives.** Leaving Dutch internships to labelling; treating "Stage" at the start of a title as English ("Stage Manager"); a radius around the Randstad instead of more city names.

**Consequences.** On the first live fetch, 20 internships are grouped (10 ING, 10 KPN), and KPN's Amersfoort Architect, DevOps, DBA and Network Security roles are shown. An English title starting with "Stage" ("Stage Manager, Events") is now treated as an internship; none exists in the stored postings, and a manager title is excluded by seniority first. Amersfoort and Hilversum are a longer commute than the Randstad cities, which labelling (`other`) can record if it matters.

---

## 27. Exclude internships that don't target CS, data or AI students; exclude architect and service desk titles

**Date:** 2026-10-11 · **Status:** Accepted

**Context.** After labelling ING and KPN, 20 labels are internships by title: 1 `yes` (ING "Power Platform Intern") and 19 `no`, all `wrong_direction` (marketing, communication, procurement, retail, private banking, corporate finance, public affairs). [docs/labeling.md](labeling.md) now says employer value and conversion paths can justify `yes` for an internship outside my core direction, as long as it targets CS students; what these 19 have in common is that their descriptions ask for other studies. Among non-internship titles, KPN "Architect" was labelled `too_senior`, "ICT stagiair(e) bij KPN Onsite Servicedesk" and Nebius "Help Desk Technician" `wrong_direction` (IT support work, which labeling.md counts as wrong direction).

**Decision.**

- A new `internship` rule (`internship_filter.require_description` in `companies.yaml`, `job_agent/internship.py`) runs after the experience rule on internships only: an internship is excluded when its description names none of computer science, informatica, informatics, software, artificial intelligence, kunstmatige intelligentie, machine learning, data science or engineering (whole words, case-insensitive). The detail is `no CS/data/AI keyword`. Regular jobs are not affected.
- The keyword list is deliberately broader than the evidence needs, so data science and AI internships are not hidden. Evaluated against `labels.jsonl`: it would exclude 16 of the 19 `no` internships and no `yes` or `maybe` job. A narrower list (computer science, informatica, software) caught all 19, but would hide a data science or AI internship that does not mention software. The 3 `no` internships still shown list Data Science or Engineering among accepted studies (ING "Stage ING Private banking - Reporting" twice, "Stagiair Hydrocarbon & New Energies"). "ICT" and "IT" are not keywords: they appear in KPN's shop and servicedesk internships.
- `title_filter.exclude_titles`: add `architect`, `servicedesk`, `service desk`, `helpdesk` and `help desk` (the `title` rule, decisions 18, 20 and 21). They catch 2 `no` labels not otherwise caught (KPN "Architect", the KPN servicedesk internship) and no `yes` or `maybe`. Whole words, so "Software Architecture Engineer" is kept.

**Alternatives.** Excluding the internship categories ING "Trainee JFG" and KPN "Stages" (decision 29); requiring a tech word in the internship's title (caught 18, but a title says less about whom the internship targets than the study requirements do); leaving internships to labelling.

**Consequences.** In the current `jobs.db`, 4 internships are shown instead of 20; 15 are excluded by the `internship` rule and 1 by `title: servicedesk`. One more shown job, KPN "Architect", is excluded by `title: architect`. An internship for CS students whose description names none of the keywords (e.g. only "IT-opleiding" or "HBO-ICT") is hidden; `review --excluded --rule internship` is how to spot one. Labelled internships stay in the evaluation set either way.

---

## 28. Experience ranges block by their midpoint

**Date:** 2026-10-11 · **Status:** Accepted. Supersedes the reading of ranges in [22](#22-exclude-jobs-that-require-3-years-of-experience).

**Context.** Decision 22 reads a range by its lower bound, so "2–5 jaar ervaring" (KPN "AI Engineer") passed the 3-year rule, yet I labelled that job `experience_required`. "2–5 years" signals a medior hire, which is different from "1–3 years".

**Decision.** A single value ("3+ years", "at least 4 years") still blocks when it reaches `min_years`. A range also blocks when its midpoint is above `min_years`: with 3, "1–3" and "2–4" pass while "2–5", "3–5" and "2–6" block. A range whose lower bound already reaches the threshold still blocks. The exclusion detail shows the range ("2-5 years"); single values keep "5+ years". Softened, optional and degree-replaceable ranges still never block. [docs/labeling.md](labeling.md) and the `experience_required` description say the same.

**Alternatives.** Keeping the lower bound (lets medior ranges through); the upper bound ("1–3 years" would block, though it is entry-level); leaving ranges to labelling.

**Consequences.** Checked before enabling: in the current `jobs.db`, exactly one shown job becomes excluded, KPN "AI Engineer" (labelled `no` / `experience_required`). No `yes` or `maybe` label has a range in its description. 9 jobs that other rules already exclude also match. A range just above the midpoint ("2–5") is treated like "4+ years", which may hide a role that would take a strong 2-year candidate; `review --excluded --rule experience` can sample those.

---

## 29. Not excluding ING Risk Management, Trainee JFG, or KPN Security, Network Engineering, IT Management and Stages

**Date:** 2026-10-11 · **Status:** Rejected

**Context.** After labelling ING and KPN, several categories had only `no` labels among the jobs shown. Excluding them (decision 14) would catch these `no` labels:

| category | `no` caught | `yes`/`maybe` excluded |
|---|---|---|
| ING Trainee JFG | 9 | 1 `yes` (Power Platform Intern) |
| KPN Stages | 10 | none |
| ING Risk Management | 1 | none |
| KPN Security | 2 | none |
| KPN Network Engineering | 2 | none |
| KPN IT Management | 1 | none |

**Decision.** Exclude none of them for now. Excluding no `yes` or `maybe` label is necessary for a rule, not sufficient:

- **ING Trainee JFG** excludes a `yes` job.
- **KPN Stages** holds all KPN internships. Excluding it goes against grouping internships rather than excluding them, and would also hide any future KPN internship for CS students; the `internship` rule (decision 27) handles the same 10 jobs by what each one asks for.
- **ING Risk Management** rests on a single label, and the category also holds model developer and "Risk AI Data Scientist" roles, which are close to ML engineering; those are currently excluded by the experience rule, not by direction.
- **KPN Security, Network Engineering and IT Management** rest on 1–2 labels each, and KPN files platform work under them: the SRE, cloud, DevOps and backup roles seen so far sit in Engineering, Network Engineering and IT Management.

**Alternatives.** Excluding each category that has only `no` labels (the option rejected here).

**Consequences.** These categories keep reaching the review queue, at the cost of a few labels per fetch. The decision is revisited when a category has enough labels to show a pattern, or when its `no` labels share a reason that a category rule would capture without hiding platform or ML roles.
