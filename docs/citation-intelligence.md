# Citation Intelligence — data model (Milestone 4A)

The foundation of the AI Search Graph: every citation an AI engine makes is
linked to a **source page** on a **source domain**, related (only when the
evidence is clear) to the customer's brand or a configured competitor, and
aggregated per project so source importance can be measured *within one
customer's market*.

```
ai_responses ──< citations ──> source_pages ──> source_domains
                    │
                    └──< citation_entities  (brand / competitor / … )
projects ──< project_sources ──> source_domains [, source_pages]
```

Code: `apps/api/app/models/sources.py`, `apps/api/app/sources/` (`normalize.py`,
`service.py`, `backfill.py`), Celery task `analytics.backfill_sources`.
Migration `60931a9b8b82`. Tests: `apps/api/tests/sources/`.

## Tables

| table | scope | key facts |
|---|---|---|
| `source_domains` | shared reference data | unique `normalized_hostname`; `hostname` as first seen; `display_name`; `domain_type`; `authority_score` (nullable, unused yet); `first_seen_at` / `last_seen_at` span all citations across all tenants |
| `source_pages` | shared reference data | unique `normalized_url`; FK → domain; `title` nullable (filled by a later milestone) |
| `citations` | tenant (`project_id`) | existing table, extended with `source_domain_id`, `source_page_id` (both nullable, `ON DELETE SET NULL`) and `extraction_confidence` (existing rows got 0.5 = unknown) |
| `citation_entities` | tenant (`project_id`) | one row per clear relationship; `entity_type` says what `entity_id` points at (`project`, `competitor`, `entity`, `name`), `relationship` ∈ brand / competitor / industry / product / unknown, `confidence` |
| `project_sources` | tenant (`project_id`) | one row per cited domain (`source_page_id NULL`) plus one per cited page; counts + first/last cited; unique `(project_id, source_domain_id, source_page_id)` with NULLs treated as equal |

Indexes: hostname, normalized_hostname, normalized_url, every `project_id`,
`source_domain_id`, `source_page_id`, `citation_count`, `last_seen_at`.

**Tenant safety.** Domains and pages carry no customer data — a hostname is a
fact about the web and is shared so that "who else cites g2.com" is answerable
later. Everything that says *who* cited a source (`citations`,
`citation_entities`, `project_sources`) carries `project_id`, and relationships
are derived only from *that* project's domains and competitors: tenant A
configuring Xero as a competitor never marks tenant B's Xero citations as
competitor citations.

## Normalisation (`sources/normalize.py`)

* hostname: lowercase, IDNA, trailing dot and leading `www.` removed. `localhost`
  and strings without a dot are rejected.
* URL: scheme lowercased (http is **not** rewritten to https — they are distinct
  pages), host normalised, default port dropped, fragment dropped, tracking
  parameters removed (`utm_*`, `fbclid`, `gclid`, `ref`, …), remaining query
  parameters sorted, duplicate slashes collapsed, trailing slash removed except
  for the root. `mailto:`/`tel:`/`ftp:` are not citations.

## Domain type

Assigned only with evidence, otherwise `unknown`:

* `company` — the host equals or is a subdomain of a project domain or a
  configured competitor's host (for the project being resolved);
* `government` / `education` — TLD evidence (`.gov`, `.gov.uk`, `.edu`, `.ac.uk`, …);
* a short curated list of well-known platforms (`reddit.com` → community,
  `g2.com` → review, `forbes.com` → media, `medium.com` → blog, …).

A domain already typed is never downgraded to `unknown`; an `unknown` domain is
upgraded when later evidence (e.g. a project that owns it) appears.

## Relationships (`citation_entities`)

Written only when the cited host is one of the project's domains (→ `brand`,
`entity_type=project`) or a configured competitor's host (→ `competitor`,
`entity_type=competitor`). Confidence 0.95 for an exact host match, 0.8 for a
subdomain. Any other citation has **no** row — "uncertain" is represented by
absence, not by a forced `unknown` relationship. `industry` / `product` are
reserved for later milestones.

## When resolution happens

* On parse: `ResponseIntelligenceService.parse_and_store` resolves the
  response's citations and rebuilds the project's `project_sources` in the same
  transaction, so new data never needs a backfill and reprocessing stays
  consistent (old citation rows are deleted, their `citation_entities` cascade).
* Historical data: `SourceIntelligenceService.backfill(project_id=None,
  force=False, batch_size=500)` resolves citations whose `source_domain_id` is
  NULL, commits per batch (resumable), then rebuilds aggregates for the touched
  projects. No AI query is re-run. Run it with
  `python -m app.sources.backfill [--project ID] [--force]` or the Celery task
  `app.workers.tasks.analytics.backfill_sources` (`dispatch_source_backfill`).
  `--force` re-resolves everything (after a normalisation change).

Upserts use `INSERT … ON CONFLICT` on the unique constraints, so concurrent
workers resolving the same host or URL cannot create duplicates.
