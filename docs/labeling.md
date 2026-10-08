# Labelling guidelines

How to label jobs with `python -m job_agent review` and `label`, so the
evaluation set for relevance scoring (decisions 15 and 17) stays consistent
over time. The reasons and their one-line descriptions live in
`label_reasons` in `companies.yaml`. This page explains how to apply them.

## Labels

| Key | Label | Use when |
|---|---|---|
| `y` | yes | I would apply. Stretch roles count, as long as no hard requirement blocks me. |
| `m` | maybe | Genuinely unsure: the direction fits but the level is unclear (e.g. demanding wording without years or senior duties). |
| `n` | no | A hard blocker exists. Needs at least one reason. |

## Reasons

**Judge direction by the actual work in the description, not the title or
category.** Titles and categories are set per company and can mislead.

- **`wrong_direction`**: the actual work is not backend/platform/infra or
  ML/AI engineering.
  - "Infrastructure" means *software* infrastructure: cloud platforms,
    distributed systems, SRE, Kubernetes, internal platforms. It does not
    mean *physical* infrastructure: optical networks, data center hardware,
    electrical/mechanical work, IT helpdesk.
  - Programming language is not a direction. A Java backend role is the
    right direction even if Java isn't my main language.
  - For full-time jobs, analysis-focused data analyst / data scientist work
    counts as wrong direction. For internships it doesn't.
- **`experience_required`**: an explicit 3+ years. 1–3 years is not a
  blocker.
- **`too_senior`**: only when no years are stated but the duties are senior
  (mentoring engineers, owning strategy, setting technical direction). If
  years are stated, prefer `experience_required`.
- **`dutch_required`**: Dutch is mandatory. "A plus" doesn't count.
- **`other`**: anything else, with a short note.

## Special cases

- **Vague wording only** ("deep experience", "highly skilled") without years
  or senior duties: label `m`, no reason.
- **Timing**: ignore it for regular full-time roles. Use `other` with a note
  only if a fixed timing constraint makes applying impossible.
