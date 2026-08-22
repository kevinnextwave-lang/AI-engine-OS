# Architecture

AI Search Growth OS is a multi-tenant SaaS built as a **modular monolith**: one FastAPI backend, one Next.js frontend, one Postgres database, Redis for background jobs and rate limiting. Modules are separated by package boundaries and queue names so the heavy parts (crawler, AI search workers, agent orchestration, analytics) can be extracted into services later without a rewrite.

## Repository layout

```
apps/web            Next.js 16 app (TypeScript, Tailwind v4, shadcn/ui)
apps/api            FastAPI app (Python 3.11, SQLAlchemy 2 async, Alembic, Celery)
packages/types      Shared TS types mirroring the API's Pydantic schemas
packages/ui         Shared shadcn/ui primitives + Tailwind theme
packages/config     Shared tsconfig base
workers/            Worker image/deployment; code lives in apps/api/app/workers
infrastructure/     Deployment notes, future IaC
docs/               This folder
scripts/            bootstrap.sh, dev.sh, check.sh
```

npm workspaces link `apps/web` to the `packages/*`. Python is a single package under `apps/api`.

## Backend layering (`apps/api/app`)

```
api/v1/routes  →  services  →  repositories  →  models
     ↑                ↑
  api/deps.py      core/*  (config, security, logging, errors, rate limiting)
```

- **Routes** are thin: parse input, call one service, shape the response.
- **Services** own business logic and transaction boundaries.
- **Repositories** own queries. Soft-deleted rows are filtered here.
- **Models** use UUID primary keys, timezone-aware UTC `created_at`/`updated_at`, and `deleted_at` for soft deletion on major entities.
- **`db/session.py`** exposes `get_db_session`, a per-request dependency that commits on success and rolls back on error.

## Data model (Milestone 1B)

```
users ──< organization_members >── organizations ──< projects ──< domains
                                                              └──< competitors
```

- `users`: email (unique), password_hash, first_name, last_name, is_active, email_verified, last_login_at, soft-delete.
- `organizations`: name, slug (unique), plan (`free|starter|growth|pro|agency|enterprise`), status (`active|suspended|deleted`).
- `organization_members`: organization_id + user_id (unique together), role (`owner|admin|member|viewer`).
- `projects`: organization_id, name, slug (unique per organization), description, industry, country, status (`active|paused|archived`).
- `domains`: project_id, url, hostname, is_primary (at most one per project via partial unique index), verified.
- `competitors`: project_id, name, website_url, hostname.

All tables have UUID primary keys and timezone-aware UTC `created_at`/`updated_at`; `organization_id`, `project_id`, `user_id`, `hostname`, and `created_at` are indexed. Foreign keys cascade on delete.

## Tenancy

`Organization` is the tenant root; `organization_members` links users to organizations with a role (`owner > admin > member > viewer`). Organization-owned tables carry `organization_id` directly (`projects`) or reach it through one join (`domains`/`competitors` → `projects`). Ownership is always resolved server-side, never by client-side filtering.

The API never trusts a client-supplied organization id. `organization_id` is read from the **URL path** and `get_current_membership` checks that the authenticated user belongs to it. Non-members get `404`, so the existence of other tenants is not leaked. `require_role(MembershipRole.X)` enforces the role hierarchy.

## Authentication

- Endpoints: `POST /api/v1/auth/signup` (validates email + password policy, creates user, organization and owner membership, starts a session), `login`, `refresh`, `logout`, `logout-all`, `GET /api/v1/auth/me`.
- Password policy in `core/passwords.py`: 10–128 chars, at least one letter and one non-letter, not a repeated character, not a common password, must not contain the user's email local part.
- Argon2id password hashing.
- Access tokens: 15-minute JWTs (`JWT_SECRET`), returned in the JSON body and kept **in memory** by the SPA.
- Refresh tokens: opaque 48-byte random strings in an `httpOnly` cookie scoped to `/api/v1/auth`. Stored as HMAC-SHA256(`JWT_REFRESH_SECRET`, token). Each refresh **rotates** the token; presenting a rotated token revokes its whole family (theft detection). Logout revokes the family; logout-all revokes every token for the user.
- Rate limiting on auth endpoints: Redis fixed window, in-memory fallback if Redis is down.
- Errors are always `{"error": {"code", "message", "details?"}}`. Invalid login returns the same body for unknown email and wrong password.
- Every auth event (signup, login success/failure, refresh, refresh reuse, logout, logout-all) is written to `auth_audit_logs` with IP and user agent, and emitted as a structured log line. Secrets never appear in either.

## Authorization

Dependencies in `api/deps.py`:

| Dependency | Resolves | Raises |
|---|---|---|
| `get_current_user` | user from Bearer JWT | 401 |
| `get_current_membership` / `get_current_organization` | caller's membership in the path `organization_id` | 404 if not a member |
| `require_role(min)` | membership with at least that role | 403 |
| `require_permission(perm)` | membership whose role holds the permission | 403 |
| `require_project_access(perm)` | project from path `project_id` **and** caller's membership in the project's organization | 404 if not a member, 403 if role lacks perm |

`organization_id` is never read from a request body; it comes from the path or is derived from the requested resource.

Permission matrix (`core/permissions.py`): **Owner** everything, including billing and ownership transfer. **Admin** manages the organization, members and projects (including delete), not billing/ownership. **Member** manages projects and data, cannot delete projects or manage members/organization/billing. **Viewer** read-only.

## Frontend

- `/login`, `/signup` — public, under the `(auth)` route group.
- `/app`, `/app/projects`, `/app/settings` — under the `(app)` group whose layout is an auth guard (silent refresh on mount, redirect to `/login` otherwise) and mounts the `AppShell`.
- `AppShell` = persistent sidebar (≥ md), sheet drawer (mobile), top bar with `OrganizationSwitcher` and `UserMenu`. The selected organization lives in `OrganizationProvider` and is remembered per browser.
- `lib/api.ts` is the only place that talks HTTP; it retries once after a transparent refresh on `401`.

### GEO section (frontend)

`/app/geo` (Overview), `/app/geo/website-audit`, `/technical-seo`, `/content`, `/structured-data`, `/ai-readiness`, grouped under "GEO" in the sidebar (`shell/nav-items.ts` supports one level of children). The pages are thin: all data loading and derivation lives in `src/lib/geo/` — `use-geo-data.ts` fetches crawl jobs, the latest technical SEO audit + observations, schema summary, entities, consistency and the latest AI readiness audit for the selected project; `mappers.ts` turns API contract types (`packages/types`) into view models (`types.ts`: `GeoIssue`, `AuditSummary`, `GeoMetric`, `CrawlOverview`, `ReadinessOverview`, `StructuredDataOverview`) and holds filtering/sorting; `labels.ts` holds category names and plain-language explanations. `ProjectProvider` (`components/project-provider.tsx`, mounted by the GEO layout) selects the project within the current organization.

**Mock vs API data.** `mock.ts` contains sample datasets typed with the same contract types. `useGeoData` returns `source: "api" | "mock"` and never mixes the two: mock data is used only when no project is selected or the API cannot be reached (network failure), and every GEO page shows a "Mock data"/"Live API data" badge plus a notice banner in mock mode. API errors (403/404/5xx) are shown as errors, not replaced by mock data. Actions (run crawl, run GEO audit = entity re-analysis + technical SEO audit + AI readiness audit, triage an observation) are disabled in mock mode.

The five overview metrics are derived, with provenance text, from: technical SEO `health_score`; AI readiness `readiness_score`; the `entity_clarity` and `content_structure` category values of the readiness breakdown; and pages-with-schema / pages-crawled from the schema summary. The issue table merges technical SEO observations (triageable via `PATCH /seo-observations/{id}`) and AI readiness observations (read-only until a triage endpoint exists). Shared primitives added to `packages/ui`: `Badge`, `Table`, `Progress`, `Skeleton`, `NativeSelect`. Charts are inline SVG/CSS (score ring, bars); no chart library or imagery is used.

## Project onboarding (Milestone 1D)

`/api/v1/projects` (list/create), `/api/v1/projects/{id}` (get/patch/delete), `/api/v1/projects/{id}/domains` (list/add), `/api/v1/projects/{id}/competitors` (list/add/remove). Creating a project requires `name` and `website_url`; the URL is normalized by `core/urls.py` (https default, lowercase punycode host, default port and fragment stripped, no IPs/localhost/credentials) and stored as the project's primary domain. Hostnames are unique per project for both domains and competitors; at most one primary domain per project. The project collection resolves the organization from the caller's memberships (`organization_id` in the body is a selector validated against membership, required only when the user belongs to several organizations). Item routes derive the organization from the project row. Domain/competitor writes need `data:manage` (member+); project deletion needs `projects:delete` (admin+).

## Website intelligence — crawler (Milestone 2 / Prompt 7)

```
POST /projects/{id}/crawl ──> crawl_jobs (queued) ──commit──> Celery "crawler" queue
                                                                  │
   worker: app.crawler.runner.run_crawl_job(job_id)               ▼
   ┌───────────┐   ┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌─────────────┐
   │ Frontier  │──>│ Robots + │──>│ Fetcher      │──>│ Parser     │──>│ Persistence │
   │ (priority │   │ per-host │   │ (SSRF-checked│   │ (selectolax│   │ crawl_urls, │
   │  + dedupe)│<──│ limiter) │   │  redirects,  │   │  links,    │   │ website_    │
   │           │   └──────────┘   │  retries,    │   │  text,     │   │ pages, page_│
   └───────────┘  links/canonical │  size cap)   │   │  hashes)   │   │ versions    │
                                  └──────────────┘   └────────────┘   └─────────────┘
```

- `app/crawler/` is self-contained (models, repositories and logging aside) so it can move to its own service later. Everything is async; the API only creates/cancels job rows.
- **Normalization** (`crawler/urls.py`): lowercase scheme/host, default ports and fragments stripped, dot-segments resolved, known tracking parameters removed (never all), remaining query sorted, trailing slash removed except root.
- **Safety** (`crawler/safety.py`): http/https only; blocked hostnames (`localhost`, `*.internal`, metadata names); DNS resolved and every address must be public (no private/loopback/link-local/multicast/CGNAT/metadata ranges, IPv4-mapped IPv6 unwrapped). Every redirect hop is re-checked. A blocked root fails the job.
- **Fetcher**: connect/read/total timeouts, streamed size cap, manual redirects (limit), retries with exponential backoff on transport errors and 408/429/5xx, `AI-Search-Growth-OS-Crawler/1.0` user agent, gzip/deflate/brotli. Only `text/html` and `application/xhtml+xml` bodies are downloaded; other types are recorded as skipped.
- **Politeness**: per-host concurrency + spacing (`requests_per_second`, `min_delay`), robots.txt with crawl-delay, cached per origin; unreachable robots (5xx) = disallow all.
- **Frontier**: priority heap (homepage 0, sitemap 1, navigation 2, content 3; slots reserved for high-value/stale/prompt-related) with a seen-set; nofollow links and `meta robots nofollow` pages do not expand.
- **Limits** come from `crawler/limits.py` per organization plan, capped by settings; the job stores the effective config.
- **Persistence**: `website_pages` is the latest version per (project, normalized_url) with `is_duplicate_of_id` for identical content hashes; `page_versions` appends a snapshot per crawl (extracted text only when content changed; raw HTML via the `HtmlStorage` interface — `none`/`local` today, object storage later).
- **Cancellation**: `cancel_requested` flag + status; the engine re-reads it every N URLs and stops scheduling; in-flight fetches finish and are recorded. Queued jobs are cancelled immediately.
- **Logs**: `crawl_started`, `url_discovered` (debug), `url_skipped`, `fetch_failed`, `page_processed`, `crawl_cancel_observed`, `crawl_completed` — URLs and counts only, never headers or cookies.

## Page intelligence (Milestone 2B)

After each successful HTML fetch the engine runs `crawler/intelligence.py::analyze_page` (pure, no I/O) and `PageIntelligenceRepository.replace_for_page` swaps the page's rows in five normalized tables:

| Table | One row per | Notes |
|---|---|---|
| `page_headings` | heading | level, document position, `parent_position` (hierarchy), text |
| `page_links` | anchor | href, normalized target, anchor text, `internal`/`external`, `status` (`unknown`/`ok`/`broken`/`invalid`), nofollow/sponsored/ugc, in-navigation flag; duplicates kept with positions |
| `page_images` | img | resolved src (incl. `data-src`/`srcset`), alt (`NULL` = attribute absent, `''` = empty), title, width/height, loading |
| `page_metadata` | page | pathname, robots, viewport, author, charset, published/modified dates, `html_lang`, resolved `language` + `language_source` (`html_lang` → `metadata` → `detected`) + confidence; Open Graph / Twitter / other metas as JSONB (open-ended shape) |
| `page_content_metrics` | page | word/character/paragraph/sentence counts, reading time, text-to-HTML ratio, heading/link/image counts, `heading_observations` JSONB (missing/multiple H1, skipped levels, duplicates, long headings — facts, not verdicts), `clean_text` |

Clean text drops scripts/styles/templates, `nav`/`header`/`footer`/`aside`/`form`, ARIA landmark roles, and cookie/consent widgets (id/class hints), prefers `<main>`/`<article>`, and keeps lists/tables/headings as line-separated blocks. Raw HTML stays behind `HtmlStorage`. Language falls back to a small stop-word detector that abstains when unsure.

Internal link status is resolved by `resolve_internal_links` at the end of every crawl (join on `website_pages`), so targets crawled later still get `ok`/`broken`. External links are never fetched. Orphan detection is deferred.

API: `GET /projects/{id}/pages` (paginated; filters `http_status`, `language`, `q`, `duplicates`), `GET /pages/{id}` (summary + metadata + metrics + headings + images + clean text), `GET /pages/{id}/headings`, `GET /pages/{id}/links` (paginated; filters `type`, `status`). Page routes derive the project from the page row and then check membership.

## Technical SEO analyzer (Milestone 2C)

`apps/api/app/seo/` turns crawl + page-intelligence data into **observations** and a health score. Nothing is fetched; an audit is a pure read of what the crawl stored, run on the `analytics` queue (`app.workers.tasks.analytics.run_seo_audit`).

- `context.py` — `build_context(session, crawl_job)` loads the project's pages, metadata, metrics, structured data, links (with an incoming-link index), and the job's `crawl_urls` (status, redirect chain, depth) plus `crawl_jobs.config["site"]` (robots/sitemap facts) into an in-memory `AuditContext`. `PageSnapshot.indexable` = 200 + not `noindex` + canonical self or absent.
- `checks/` — pure functions `(AuditContext) -> list[Finding]`, one module per area: `metadata` (missing/duplicate/length of titles and descriptions), `headings` (H1 missing/multiple, skipped levels, duplicates, long), `canonical` (missing, conflicting, external, chained, non-200 target, mismatch), `http` (4xx/5xx grouped by status, redirect chains/loops) + `indexability` (robots.txt unreachable/missing, robots-blocked URLs, noindex share, no sitemap), `links` (orphans, weakly linked, broken internal links per page, excessive depth), `structured` (invalid blocks, detected types, pages without any) and `mobile_html` (viewport, lang, charset, doctype, multiple titles). Each finding carries a `code`, a context-dependent severity, evidence (URLs, counts, lengths) and a concrete recommendation — no generated text.
- `scoring.py` — Technical SEO Health Score, computed only from the findings; methodology in `docs/technical-seo-health-score.md`, full breakdown stored on the audit.
- `engine.py` — `run_audit`: `running` → context → checks → score → `seo_observations` rows + summary → `completed`, or `failed` with the error recorded.

Tables: `seo_audits` (project, crawl job, status, pages analyzed, observation count, `health_score`, `score_breakdown`, `summary`) and `seo_observations` (audit, project, optional page, URL, category, code, severity, title, description, evidence JSONB, recommendation, triage `status` open/ignored/resolved + note + user). Inputs added to the crawler for this milestone: `crawl_urls.final_url`/`redirect_chain`, `page_metadata.has_doctype`/`title_count`/`canonical_count`/`canonical_url`, `page_structured_data` (JSON-LD/Microdata/RDFa blocks, parsed types, validity), and robots/sitemap facts in `crawl_jobs.config.site`.

API: `POST /projects/{id}/seo-audits` (DATA_MANAGE; body `crawl_job_id` optional, defaults to the latest finished crawl; 409 if that crawl has not finished; commits then dispatches, dispatch failure → `failed`), `GET /projects/{id}/seo-audits`, `GET /seo-audits/{id}`, `GET /seo-audits/{id}/observations` (severity-ordered; filters `category`, `severity`, `status`; paginated), `PATCH /seo-observations/{id}` (DATA_MANAGE; status + note). Audit/observation routes derive the project from the row and check membership (404 for other tenants).

## Structured data and entity intelligence (Milestone 2D)

`apps/api/app/entities/` reads the `page_structured_data` rows a crawl stored and rebuilds, per project, a derived layer in four tables: `entities` (one per typed node: `entity_type`, `extra_types`, `name`, `description`, `url`, `same_as`, `identifier`, `properties` JSONB, `json_path`, `fingerprint` = type + normalized name, `scope` `page`|`project`), `entity_links` (each sameAs URL classified by platform — linkedin, wikipedia, wikidata, x, facebook, crunchbase, … — with an `is_authoritative` flag for knowledge-graph/registry profiles), `schema_issues` (structural validation per block) and `entity_observations` (cross-page findings). Everything is deleted and recreated on each run, so the layer is always a function of the current crawl.

- **Inputs.** JSON-LD is parsed at crawl time (`payload` stored, parse errors recorded). Microdata and RDFa Lite are now extracted into JSON-LD-shaped items (`@type` + properties, nested scopes become nested objects) by `crawler/intelligence.py::_extract_attribute_items`, so all three formats feed the same pipeline. JSON-LD is the primary source; attribute formats are best-effort.
- **Validation** (`validation.py`) covers structure only: unparseable/invalid JSON, non-object roots, missing `@context`, non-schema.org context (info), missing `@type` on objects that carry properties, invalid `@type` values, `@graph` that is not an array, nested arrays-in-arrays, empty values, excessive depth. It makes no claim about rich-result eligibility; the API responses say so explicitly.
- **Extraction** (`extraction.py`) turns every typed node (root, `@graph` member, nested object) into an entity; nested typed nodes are replaced in the parent's `properties` by a compact `{"@ref": true, "@type", "name"}` reference so nothing is duplicated. `identifier` collects `identifier`/`@id`/`sku`/`gtin*`/`isbn`/`mpn` (PropertyValue → `propertyID:value`). `is_known_type` marks the schema types the product tracks (Organization, Person, Product, Service, Article, BlogPosting, FAQPage, BreadcrumbList, LocalBusiness, WebSite, WebPage, Review, AggregateRating, Offer, Event); absence of a type is reported as information, never as a defect.
- **Consistency** (`consistency.py`) groups page entities by fingerprint. Within a page, repeated declarations become `duplicate_entity` (low). Across pages, properties that are facts (everything except page-specific keys such as `mainEntityOfPage`, dates, `position`, `offers`, `review`…) are compared after whitespace/case normalization; differing values become `entity_value_conflict` — title "Potential factual inconsistency" (medium) — listing every observed value with its source pages. Differing `sameAs` sets are `same_as_inconsistent` (info). No value is chosen as correct.
- **Project organization** (`organization.py`) consolidates one `scope=project` entity from Organization-like schema, preferring the homepage, then about/company pages (`/about*`, `/company`, `/team`…), then any page whose organization `url` is on the project's root host; it merges `legalName`, `logo`, `telephone`, `email`, `address`, `foundingDate`, founders, identifiers and the union of sameAs, records every `_sources` entry and `_conflicts`, and adds `_signals` (homepage schema present, about/contact page URLs, e-mails/phones found in the visible text of those pages) and a `_confidence` of high/medium/low. It falls back to the project name when no schema names the organization. This entity is the seed for the future AI Reputation module.

Runs on the `analytics` queue (`app.workers.tasks.analytics.run_entity_analysis`), dispatched automatically by the crawl task when a crawl finishes (completed or partially completed) and on demand via `POST /projects/{id}/entity-analysis` (DATA_MANAGE). No external AI or network calls.

API (DATA_READ; project derived from path or page row): `GET /projects/{id}/entities` (filters `type`, `scope`, `known_only`; paginated; includes the project organization with its classified links and `analyzed_at`), `GET /projects/{id}/schema` (coverage and format/type counts, known types present/absent, validation issues with page URLs), `GET /pages/{id}/schema` (each block with payload, issues and extracted entities), `GET /projects/{id}/entity-consistency` (observations + number of entities compared).

## AI search readiness analyzer (Milestone 2E)

`apps/api/app/ai_readiness/` is a deterministic analysis of the data already collected (pages, page intelligence, structured data, the 2D entity layer). **It does not query any AI system**; that is the later AI Visibility engine. `context.py` builds `PageSnapshot`s (text, headings, metadata, schema types, page entities, external links) and classifies each page into kinds — home, product, service, pricing, article, about, contact, faq, case_study, comparison — from path patterns, schema types and title/H1 patterns. `signals.py` holds the lexical detectors (audience, geography, contact, features, pricing, use cases, integrations, bylines, credentials, dates, statistics, research, original data, citations, case studies, customer evidence, FAQ headings, question headings, specificity). `analyzers.py` produces observations in eight categories — `entity_clarity`, `product_clarity`, `authority`, `evidence`, `faq`, `comparison` (recorded, never judged or scored), `content_structure` (specificity measurements, thin and unstructured pages) and `factual_consistency` (from 2D entity conflicts) — each with a deterministic recommendation and the evidence it rests on. Wording is restricted to signal language ("entity clarity", "citation readiness", "AI readability signal"); no observation claims a ranking effect.

Tables: `ai_readiness_audits` (status, pages analyzed, observation count, `readiness_score`, `score_breakdown`, `summary` incl. page kinds) and `ai_readiness_observations` (audit, project, optional page, category, code, severity, title, description, evidence, recommendation). The **AI Readiness Score** is an internal weighted coverage metric documented in `docs/ai-readiness-score.md`; inapplicable categories are excluded and the breakdown stores every input.

API: `POST /projects/{id}/ai-readiness-audits` (DATA_MANAGE; 422 without crawled pages; commit then dispatch on the `analytics` queue), `GET /projects/{id}/ai-readiness-audits`, `GET /ai-readiness-audits/{id}` (audit + severity-ordered observations; filters `category`, `severity`). Audit routes derive the project from the audit row; other tenants get 404.

## AI provider abstraction (Milestone 3A)

```
AI Search Service (later)  →  app/services/ai.py::AIGenerationService
                                   │  resolves provider + model from ai_providers / ai_models
                                   ▼
                          app/ai/base.py::AIProvider.generate(AIRequest) -> AIResponse
                 ┌──────────────────┼──────────────────┐
        providers/openai.py  providers/anthropic.py  providers/google.py   (REST via httpx, no SDKs)
```

- **Interface** (`app/ai/types.py`, `base.py`): `AIRequest` (request_id, model, prompt, system_prompt, temperature, max_tokens, timeout_seconds, metadata) → `AIResponse` (provider, model, response_text, finish_reason, input/output/total tokens, latency_ms, provider_request_id, small `raw_response` metadata, `error`). `AIProvider.generate` is the only entry point: it normalizes the request against the adapter's `ProviderCapabilities` (drops or clamps temperature, caps output tokens, folds system instructions into the prompt where unsupported), enforces a wall-clock timeout, converts every failure into an `AIError` with one of seven categories — `authentication_error`, `rate_limit`, `timeout`, `provider_error`, `invalid_request`, `content_filter`, `unknown_error` — and emits one structured `ai_generation` log line (provider, model, request id, success, latency, tokens, error category). Provider payloads and exception classes never leave `app/ai/providers/*`; `raw_response` carries only a few neutral fields, never the full body.
- **Adapters** map parameters per vendor (OpenAI `max_completion_tokens`, Anthropic mandatory `max_tokens` and 0–1 temperature, Gemini `generationConfig`/`systemInstruction`) and finish reasons (`stop`/`end_turn`/`STOP`, `length`/`max_tokens`/`MAX_TOKENS`, content filters incl. Gemini `promptFeedback.blockReason`). API keys travel in headers only (never query strings) and are read from `SecretStr` settings: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_AI_API_KEY`; base URLs and default models are settings too (`*_DEFAULT_MODEL`).
- **Registry** (`app/ai/registry.py`): builds an adapter per configured key; `get()` raises normalized errors for unknown or unconfigured providers. Adding a vendor = one adapter class + one factory entry; `register()` injects instances for tests.
- **Catalogue** (`ai_providers`, `ai_models` with JSONB `capabilities`, both with `is_enabled`): seeded by the migration from `app/ai/catalog.py` (single source of truth, also used by tests). Model-level capabilities (`max_output_tokens`, `max_temperature`, `supports_temperature`) cap requests in the service. No credentials are stored in the database.
- **Generation log** (`ai_generations`): one row per call — provider/model keys and ids, purpose, success, finish reason, error category/message, tokens, latency, provider request id, request metadata; prompt/response text is stored only when `AI_STORE_RESPONSE_TEXT` is true (the caller can override per call). Resolution failures (disabled provider/model, unknown model, missing credentials) are recorded and returned as failed `AIResponse`s so callers handle one shape.

Not yet built: prompt generation, visibility scoring, any HTTP endpoint. Tests (`tests/ai/`) use `httpx.MockTransport` only; no real provider is called.

## Prompt intelligence (Milestone 3B)

Hierarchy `projects → prompt_sets → prompts → prompt_runs` (`app/models/prompts.py`). `prompt_sets` carry name/description/optional focus `category`/`status` (draft|active|archived) plus the `generation_profile` used last; `prompts` carry `text`, a per-set-unique `normalized_text`, `category` (discovery, comparison, recommendation, pricing, product, alternative, problem_solution, industry, local, transactional), `intent` (informational, commercial, transactional, navigational), `funnel_stage` (awareness → retention), `language`, `country`, `priority` 1–5, `is_active`, `source` (generated|manual), `quality_score` + `quality_breakdown`; `prompt_runs` (status, provider/model, link to `ai_generations`, `visibility` JSONB) are created by the AI Visibility engine later.

`app/prompts/`: `profile.py` turns the inputs (company name, website, industry, products, services, features, use cases, integrations, target audience, competitors, geographic market) into buyer vocabulary — offering nouns with singular/plural variants ("accounting software" → "accounting platforms"/"accounting tools"), brand products, task phrases, geo phrases with articles. `generator.py` fills ~35 journey templates grouped by category and funnel stage, rotating slot values round-robin so output is diverse, and drops exact/near duplicates (incl. against prompts already in the set). `classify.py` infers category/intent/stage for manual prompts by rule. `normalize.py` provides normalization and Jaccard near-duplicate detection (no embeddings). `quality.py` scores each prompt (relevance, uniqueness, commercial intent, specificity, geographic relevance) and derives priority — `docs/prompt-quality-score.md`.

`PromptService` builds the profile from project data (name, primary domain, industry, country, competitors table, Product/Service entities from the crawl) with request overrides winning, generates into a set, and handles manual CRUD with inference, duplicate rejection (409) and re-scoring on edits. API: `POST/GET /projects/{id}/prompt-sets`, `POST /prompt-sets/{id}/generate`, `GET|POST /prompt-sets/{id}/prompts`, `PATCH|DELETE /prompts/{id}`. Rows are table-ready (prompt, category, intent, funnel stage, priority, status, last run, visibility result). Set/prompt routes derive the project from the row; DATA_READ / DATA_MANAGE apply; other tenants get 404. No AI provider is called.

## Prompt execution engine (Milestone 3C)

```
POST /prompt-sets/{id}/run ──> prompt_run_batches + prompt_runs (queued) ──commit──> Celery "ai_search" queue (priority 3/5/9)
                                                                                         │
     worker: app.ai.execution.execute_prompt_run(run_id)                                 ▼
     throttle (per-provider RPM, Redis) → claim run (UPDATE … WHERE status='queued') → AIGenerationService
     → ai_responses + ai_usage_records + batch counters → completed | failed | requeued with backoff
```

- **Tables.** `prompt_run_batches` (project, prompt set, status queued|running|completed|failed|cancelling|cancelled, priority, `targets`, total/completed/failed/cancelled counters, timestamps); `prompt_runs` gained batch, provider/model ids, attempts, latency, `error_code`, and the `cancelled` status; `ai_responses` (one per completed run: text, finish reason, tokens, latency, provider request id, neutral `raw_metadata`); `ai_usage_records` (organization, project, run, provider, model, tokens, `estimated_cost`, currency, `pricing_version`). `ai_models.pricing` holds per-million-token rates — the only place prices live (`app/ai/pricing.py::estimate_cost`; defaults seeded from `app/ai/catalog.py`).
- **Batch creation** (`ExecutionService.run_prompt_set`): validates providers (known, enabled, credentials configured) and models (catalogue, enabled; defaults from settings), creates one run per active prompt × target, commits, then enqueues each run with the batch's Celery priority; if the broker fails mid-way the un-enqueued runs are marked `failed` (`dispatch_failed`) rather than left queued forever.
- **Execution** (`execute_prompt_run`) never sleeps on a worker: a throttled provider or a retryable error returns `Outcome.retry_in`, and the Celery task re-schedules itself with `self.retry(countdown=…)` (exponential backoff, `AI_RUN_RETRY_BASE_SECONDS` × 2ⁿ capped by `AI_RUN_RETRY_MAX_SECONDS`, at most `AI_RUN_MAX_ATTEMPTS`). Rate-limit, timeout and provider errors retry; authentication, invalid-request, content-filter and unknown errors fail immediately. The claim is an atomic `UPDATE … WHERE status = 'queued'`, so a late worker can never resurrect a cancelled run.
- **Cancellation** (`POST /prompt-run-batches/{id}/cancel`): batch → `cancelling`; every still-queued run → `cancelled` immediately; runs already inside a provider call finish, their answer and usage are kept, and the batch is finalized as `cancelled` when the last one reports back. A queued run that observes a cancelling batch before calling the provider cancels itself.
- **Observability**: `prompt_batch_created`, `prompt_run_completed` (latency, tokens, cost), `prompt_run_retry`, `prompt_run_failed` — never prompts, responses or keys.

API: `POST /prompt-sets/{id}/run` (DATA_MANAGE; 202 with the batch), `GET /prompt-sets/{id}/batches`, `GET /prompt-run-batches/{id}` (counters + aggregated usage), `GET /prompt-run-batches/{id}/runs` (runs with responses; filter `status`), `POST /prompt-run-batches/{id}/cancel`. Tenancy is derived from the prompt set / batch row. Worker command: `celery -A app.workers.celery_app:celery_app worker -Q ai_search`.

## AI response intelligence parser (Milestone 3D)

`apps/api/app/intelligence/` turns a stored `ai_responses.response_text` into observations, in two stages:

1. **Deterministic** (`deterministic.py`): markdown structure (headings, ordered/bullet list items with 1-based positions, `Sources:`/`References:` lists with entry positions), URLs, markdown links, bare domain references, brand/competitor strings (project name + domain stem + hostname aliases; competitors from the `competitors` table), lexical sentiment and recommendation-strength cues per sentence ("the best"/"top pick" → strong, "a good option" → moderate, "one option"/"also consider" → weak, negative cues → none), and simple `<Brand> <verb> <object>` claims. A mention gets a position only when the brand is the subject of a list item; prose mentions and in-passing mentions keep `position = null` — rankings are never invented. Absent brand ⇒ overall sentiment `unknown`, never negative.
2. **AI-assisted** (`interpreter.py`, opt-in via `AI_PARSER_LLM_ENABLED`): runs only when Stage 1 leaves judgements unknown or the answer is prose. The LLM must return JSON matching `LLMInterpretation` (Pydantic, `extra="forbid"`); malformed or off-schema output is recorded in `stage2_error` and discarded. Validated output can only refine sentiment/strength of mentions Stage 1 already found, set positions when the model states the ranking is explicit, and add claims about known brands — it cannot introduce brands or citations, and it never touches state directly.

Output is a strict `ParsedResponse` (mentions, competitor mentions, claims, citations typed `explicit_url|markdown_link|domain_reference|source_list|unknown`, recommendations in answer order, overall sentiment, position signals, `parser_version`). `ResponseIntelligenceService.parse_and_store` writes `brand_mentions`, `competitor_mentions`, `claims`, `citations` (every row stamped with `parser_version`), stamps `ai_responses.parser_version/parsed_at/parse_summary`, and fills `prompt_runs.visibility` (brand mentioned, position, sentiment, competitors) for the prompt table. The execution engine calls it after each completed run; failures there never undo the run. **Reprocessing** (`parse_and_store(force=True)`, `reprocess_batch`) deletes and rewrites the observation rows for a response under the current `PARSER_VERSION` — the `ai_responses` row is never duplicated.

API: `GET /prompt-runs/{id}/intelligence`, `POST /prompt-runs/{id}/reprocess`, `POST /prompt-run-batches/{id}/reprocess` (tenant derived from the run/batch row; DATA_READ / DATA_MANAGE).

## AI Visibility Engine (Milestone 3E)

`apps/api/app/visibility/` computes the **AI Visibility Score** — this product's own composite metric, documented in full in `docs/ai-visibility-score.md` (`ai-visibility-score/v1`). Nothing is persisted: `observations.py` loads one row per completed, parsed prompt run (joined to prompt, brand/competitor mentions and citations); `metrics.py` is pure computation (mention rate, recommendation rate, position score, citation rate, sentiment, competitive score, weights 25/25/15/15/10/10 with unavailable components renormalised); `engine.py` adds the time dimension (7/30/90-day current vs previous period, change, trend, weekly series) and breakdowns (provider, model, prompt, category, funnel stage, competitor share).

Data sufficiency is first-class: below 5 eligible responses the score and rates are `null`, not 0; small samples are rounded coarsely; every payload carries `data_quality` (sample size, sufficiency, providers, models, prompts, date range, parser versions). Unconfigured competitors never lower the score.

Routes (`routes/visibility.py`, read-only, `DATA_READ`): `GET /projects/{id}/visibility`, `/visibility/trends`, `/visibility/by-engine`, `/visibility/by-prompt`, `/visibility/competitors`, all with `?window=7d|30d|90d`. Tests seed parsed observations directly (`tests/visibility/seed.py`) — no providers, no parser. Two small supporting routes serve the UI: `GET /prompts/{id}/runs` (a prompt's run history with responses, newest first) and `GET /ai/providers` (which providers this deployment has configured — a boolean per key, never a credential).

### AI Visibility frontend (`apps/web`)

Navigation group **AI Visibility** → Overview, AI Engines, Prompts, Competitors, Trends (`src/app/(app)/app/ai-visibility/*`). Same layering as the GEO section: `src/lib/visibility/` holds the view-model types, pure mappers (API contract → view models), clearly labelled sample data, and the `useVisibilityData` hook that loads the five visibility endpoints plus prompt sets/prompts and provider status for one project + window. Components in `src/components/visibility/` only render. Provenance is explicit (`source: "api" | "mock"`, the Mock badge and notice); a selected project with zero eligible responses shows the "Run your first AI Search analysis" empty state — never sample numbers — with *Run Prompt Set* enabled only when a prompt set has active prompts and the server has a configured provider. Every metric tile shows value, previous-period change and sample size; `null` renders as "–" with the reason. The trend chart is an inline SVG (no chart dependency) with overall / by-engine / vs-competitors series from `/visibility/trends`. Clicking a prompt opens the response drawer: run history (`/prompts/{id}/runs`), the stored answer with brand, competitor, citation and claim highlights (`src/lib/visibility/highlight.ts`, pure), and the parsed analysis from `/prompt-runs/{id}/intelligence`.

## Citation Intelligence data model (Milestone 4A)

`apps/api/app/models/sources.py` + `apps/api/app/sources/`: every citation is linked to a `source_page` on a `source_domain` (shared reference data, unique by normalised hostname / URL), related to the brand or a configured competitor only when the cited host proves it (`citation_entities`; uncertain = no row), and aggregated per project in `project_sources` (domain-level and page-level counts, brand/competitor citation counts, first/last cited). Resolution runs inside the parse transaction for new responses; `SourceIntelligenceService.backfill` (CLI `python -m app.sources.backfill`, Celery `analytics.backfill_sources`) links historical citations without re-running any AI query. Tenant-scoped tables carry `project_id`; relationships are derived only from that project's own domains and competitors. Full description in `docs/citation-intelligence.md`.

### Source classification (Milestone 4B)

`app/sources/registry.py` loads a configurable registry (`registry.json`, extendable via `SOURCE_REGISTRY_PATH`); `classify.py` turns seven signals (project host, TLD, registry, hostname prefix, URL path, page title, page metadata) into weighted evidence, combines it with a noisy-OR and only assigns a type above a threshold — otherwise `unknown`, with probabilities and evidence stored on `source_domains.classification`. `relevance.py` computes the transparent **Source Relevance Score** (frequency, breadth, consistency, source type, optional project frequency — explicitly not a domain-authority score). `GET /source-domains/{id}` returns the profile, scoped to the caller's projects except for two cross-tenant counts.

## Citation Gap Engine (Milestone 4C)

`apps/api/app/gaps/`: for one project and window, aggregates stored citations per source domain (relevant responses, prompts, brand vs competitor citations from `citation_entities` — now also recognised from brand/competitor names in third-party URL paths), classifies each source into a gap type (`brand_absent`, `competitor_advantage`, `shared_source`, `source_underrepresented`, `source_overrepresented`, `emerging_source`), computes the transparent **Citation Opportunity Score** (citation frequency, competitor gap, source relevance, prompt relevance, recency; type multipliers so volume alone is never a recommendation) and a sample-size-driven confidence (`high`/`medium`/`low`/`insufficient`), and upserts `citation_gaps` keeping status/notes. Routes: list with filters, summary, analyze, get, patch. Methodology in `docs/citation-gaps.md`.

## AI Search Graph v1 (Milestone 4D)

`apps/api/app/graph/queries.py` exposes the observed data as a graph without a graph database: nodes are existing rows (projects, prompts, responses, brand/competitor mentions, claims, citations, source pages/domains) and edges are the foreign keys and link tables between them. `GraphQueryService` answers the six graph questions (most-cited sources, competitor-associated sources, competitor-vs-brand gap sources, prompts producing competitor citations, rising sources, repeated claims) with windowed, paginated SQL, and `/graph/overview` returns a bounded node/edge subgraph with statistics. Routes under `/projects/{id}/graph/*` (DATA_READ). `docs/ai-search-graph.md` documents the model, the queries and the migration path to Apache AGE / Neo4j.

## Background jobs

Celery app in `apps/api/app/workers/celery_app.py` with Redis as broker/backend. Tasks are routed by module name to the `crawler`, `ai_search`, `agents`, and `analytics` queues. `app.workers.tasks.crawler.run_crawl_job` runs crawls on the `crawler` queue (acks-late, 6h hard limit); `app.workers.tasks.analytics.run_seo_audit` runs SEO audits and `app.workers.tasks.analytics.run_entity_analysis` rebuilds entity intelligence and `app.workers.tasks.analytics.run_ai_readiness_audit` runs readiness audits on the `analytics` queue; `app.workers.tasks.ai_search.run_prompt` executes prompt runs on the priority-enabled `ai_search` queue (30 min limit); `ping` remains for health checks.

## Environments

Configuration is read exclusively through `app/core/config.py` (pydantic-settings). Production refuses to start with development secrets. See the root `.env.example` for the variable list.

## Deployment

- `apps/web` → Vercel.
- `apps/api` → Railway (`railway.toml` runs migrations, then uvicorn). Worker = same image, Celery entrypoint (`workers/Dockerfile`). Postgres and Redis as Railway plugins.
