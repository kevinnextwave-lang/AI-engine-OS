# Entity Optimization Agent (Milestone 6E)

Identifies weaknesses in how the customer's **organization, products, services
and people** are represented across the site's crawled entities, structured
data, pages and links — and where declarations **conflict** between pages. It
modifies nothing; every proposed modification requires human approval.

Code: `apps/api/app/agents/entity_optimization.py` (registered as
`entity-optimization`, run via the generic agent endpoint), model
`app/models/entity_reviews.py` (`entity_optimization_reviews`, migration
`d1d1307fed64`), routes `app/api/v1/routes/entity_reviews.py`.

## What is checked (all from observed data)

* **Organization** — name, description, website URL, logo, contact information
  (contactPoint/email/telephone), sameAs / social profiles (entity sameAs +
  `entity_links`), location (address), founding information (flagged as
  optional: "add only if the real founding date is known — do not guess"),
  industry (against the project profile). When no Organization entity exists at
  all on a crawled site, that absence is itself a high-confidence finding with
  the "Add appropriate Organization structured data" recommendation.
* **Products** — name, description, features (featureList), audience, pricing
  (offers/priceRange), URL, and the relationship to the organization
  (brand/publisher/manufacturer → "Connect product entities to organization").
  Product-like pages (product/pricing/features URLs) without any Product entity
  get their own finding.
* **Services** — definition, target customer (audience), geographic scope
  (areaServed), related organization (provider).
* **People** — only Person entities that actually exist are reviewed
  (role/title, organization link); recommendations say to add **real, current
  information** and never suggest credentials.
* **Consistency** — organization declarations are compared across pages
  (homepage, about, product, contact — wherever they appear) and against
  metadata: conflicting names, conflicting descriptions and inconsistent
  sameAs sets each become findings with the conflicting values and their page
  URLs, recommending one canonical declaration ("Resolve conflicting company
  information"). No conflicts → no consistency review.

Supporting tools added to the registry: `get_entity_data` now returns url,
scope, page linkage and a whitelist of schema.org properties;
`get_entity_links` lists sameAs/profile links; `save_entity_review` is the
validated write path (project-scoped, `entity_id` ownership checked, draft on
insert, status preserved on re-save; unique per project + review_key).

## Language rules

Every recommendation carries the note that the changes make information
explicit and machine-readable and that **how any engine interprets them is
not guaranteed** — no unsupported claims about search behavior, no invented
founding facts, credentials or contacts (missing data is always an
instruction to supply real information).

## Human review

Reviews are drafts; `PATCH /entity-reviews/{id}` moves them through draft →
reviewing → approved → completed → archived, and each run proposes a
medium-risk `review_entity_optimization` action per review, so runs end
`awaiting_approval` until a person decides. Re-runs upsert by review_key and
never reset a review's status.

## API

`GET /projects/{id}/entity-reviews` (filters `status`, `entity_type`),
`GET /entity-reviews/{id}`, `PATCH /entity-reviews/{id}`. Non-members 404.

## Tests

`apps/api/tests/agents/test_entity_optimization.py`: organization analysis
(present aspects not flagged, missing ones flagged, founding marked optional,
no engine-behavior claims), missing organization entirely, product analysis
(all aspect checks + both flagship recommendations), product pages without
Product entities, consistency (conflicting names/descriptions/sameAs with
page-level conflict lists) and its absence when declarations agree,
recommendations + approval workflow + re-run upsert with surviving status,
and authorization.
