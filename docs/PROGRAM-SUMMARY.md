# AI Search Growth OS — Engineering Program Summary

**Date:** September 27, 2026 · **Final state:** 644 API tests passing / 1 xfailed · web typecheck, lint, production build green · mypy clean (274 files) · 10 Alembic migrations, all `alembic check`-clean · every feature below verified live against a running stack, not just in tests.

This is the handoff document: what shipped, why, and what's honestly still open. It covers the work since the read-only launch audit (the earlier UI/UX program — responsive/a11y/dark-mode passes and roadmap phases A–G — is summarized in the audit document and the per-phase commit messages).

---

## The arc

A read-only pre-launch audit (four parallel deep-dives: auth/security, tenant isolation, crawler/AI pipeline, ops/billing/legal) found the fundamentals unusually strong — clean tenant isolation across all 27 route files, robust SSRF protection, a solid auth core — and six launch blockers that were operational rather than architectural. Everything the audit raised, at every priority level, has since been fixed, tested, and live-verified. Then the product gaps around it were closed: billing, teams, grounded AI measurement, onboarding, and CI/CD.

## What shipped (29 commits, oldest first)

**Pre-audit tail:** navigation wayfinding (a13b356), final verification sweep (494ad6a), dark mode wired and axe-clean (a2174dd), VERIFY data-model additions (bbbc5f9), session cache for the heavy loaders (c278896).

**P0 — launch blockers:** production deploy safety rails — APP_ENV defaults, placeholder-secret rejection (3ac8238); celery beat actually running + QUEUED-orphan reaping (aac3ed8); web builds fail loudly without the API URL, no sample data in production (224d9e3); AI cost controls — per-user rate limits, batch caps, one batch per project, per-org daily budget (53ad53c); email + password reset + verification (7b06612); legal pages + self-serve account/org deletion (1af289f).

**P1 — hardening:** immediate access-token revocation via token_version, CSRF origin guard, security headers (da3ad2c); real readiness probe, fail-safe rate limiter with Redis reconnection, per-account login throttle (5ca9235); honest PARTIAL batch status + Retry-After-aware retries (acddd56); env-gated Sentry, request IDs, structured access log, web error boundaries (6547c6d); migration advisory lock, non-root images, bootstrap fix (5cff4a1); test isolation fix (83cb4e0).

**Product:** Stripe billing with per-plan limits and the suspend/recover lifecycle (8eed410); the deploy runbook (cacd1dc, `docs/DEPLOY.md`); grounded AI search — Perplexity + Gemini grounding (4620881) and OpenAI web-search models (905e408), with provider-retrieved citations stored distinctly from model-memory URLs and labeled honestly in the UI; team invitations, member removal, role changes with last-owner protection (ae44274); data-driven onboarding checklist + command palette (c7a362d).

**P2 — audit backlog cleared:** standard-ports-only URLs + off-site redirect containment (7a83771); settings-driven data retention on beat (da98ebb); optional HIBP breached-password check (7d0f2b4); the three missing cross-tenant write tests (dd909be).

**Reliability + CI/CD:** per-org AI throttle, partial-batch banner, operator webhook on reaper firings (59ce4ac); release workflow — GHCR images gated on green CI, optional Railway/Vercel auto-deploy (dc720c5).

## Principles that held throughout

Nothing is claimed fixed unless implemented and re-verified — most features got a live end-to-end check on a running stack (real crawls, real emailed tokens, real webhook lifecycles) on top of tests. Measurements never lie: unavailable is "–" and never zero, partial collections say so, provider-retrieved citations are distinguished from URLs a model wrote from memory, and no metric is invented client-side. Every emailed credential (reset, verify, invite) is single-use, HMAC-hashed at rest, and expiring. Safety rails fail the right way: production checks fail closed (boot refusal, build failure), monitoring fails open (a broken breach-check API or ops webhook never blocks users).

## Honestly still open

The legal pages carry a placeholder contact address and need counsel review before charging. Stripe needs its two products created and four env values set (test mode works end-to-end today). Email verification is soft — nothing blocks unverified accounts yet. A strict script-src CSP awaits nonce plumbing for the theme bootstrap. Grounded pricing in the catalog is the token floor; per-request search fees for search-preview/Perplexity tiers should be reflected in `ai_models.pricing` per your contracts. The crawler has been validated against a controlled site plus the safety test-suite, not yet against a broad set of hostile real-world sites — do that during beta (the runbook says how). One order-dependent test flake in discovery remains (passes isolated; pre-existing).

## Operating the thing

`docs/DEPLOY.md` is the runbook. `/health/ready` is the readiness truth. The worker must run exactly one beat (`-B` is embedded in the image; split it before scaling replicas). `OPS_WEBHOOK_URL` tells you when workers died unobserved. Retention, budgets, throttles, HIBP, Sentry, and billing are all env-switched — `.env.example` documents every knob.
