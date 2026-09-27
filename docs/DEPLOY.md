# Beta Launch Runbook

Deploying AI Search Growth OS to production: **Railway** (API + worker + Postgres + Redis), **Vercel** (web), with email, Stripe, and Sentry as switch-ons. Written against the code as of September 2026 — every env var named here exists in `apps/api/app/core/config.py`, and the startup checks described are real: the API **refuses to boot** in production with placeholder secrets, insecure cookies, wildcard CORS, or a localhost database URL.

Time budget: ~90 minutes for a first full deploy, most of it waiting on DNS.

---

## 0. Decide your domains first

The refresh-token cookie makes this the one decision that changes configuration everywhere. Two workable setups:

**A. Subdomains of one domain (recommended):** `app.yourdomain.com` (web) and `api.yourdomain.com` (API). Same registrable domain = same site, so the default `COOKIE_SAMESITE=lax` works and CSRF exposure is minimal. Use this.

**B. Platform domains** (`something.vercel.app` + `something.up.railway.app`): different sites, so you MUST set `COOKIE_SAMESITE=none` (the API enforces `COOKIE_SECURE=true` alongside it, and the Origin guard on the cookie endpoints protects against CSRF). Works, but move to A before real users if you can.

## 1. Generate secrets (on your Mac)

```bash
# Two different values — the API refuses identical or placeholder secrets.
openssl rand -base64 48   # -> JWT_SECRET
openssl rand -base64 48   # -> JWT_REFRESH_SECRET
```

## 2. Railway — database, Redis, API

1. New Railway project → **Add PostgreSQL** and **Add Redis** (plugins).
2. **New service → GitHub repo**, root directory `apps/api`. `railway.toml` is picked up automatically: Dockerfile build, healthcheck on **`/health/ready`** (real readiness — checks Postgres and reports Redis), and migrations run before serving. The image itself defaults to `APP_ENV=production`, so the safety checks run even if you set nothing.
3. Service → Variables:

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (redundant with the image default; set it anyway for clarity) |
| `DATABASE_URL` | reference → `${{Postgres.DATABASE_URL}}` (plain `postgres://` is auto-upgraded to asyncpg) |
| `REDIS_URL` | reference → `${{Redis.REDIS_URL}}` |
| `JWT_SECRET` / `JWT_REFRESH_SECRET` | the two generated values |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `lax` for setup A · `none` for setup B |
| `CORS_ORIGINS` | `https://app.yourdomain.com` (comma-separated if several) |
| `WEB_BASE_URL` | `https://app.yourdomain.com` (used in emailed reset/verify links; production refuses localhost here once a real email backend is set) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_AI_API_KEY` | whichever providers you'll offer (a provider without a key is cleanly rejected at run time with "no credentials configured") |
| `AI_DAILY_COST_LIMIT_USD` | operator ceiling on top of plan budgets; `25` is a sane beta default |

4. Settings → Networking → add custom domain `api.yourdomain.com` (Railway gives you the CNAME).

## 3. Railway — worker (one more service, same repo)

1. **New service → same GitHub repo**, root directory **`/`** (repo root — the worker Dockerfile copies from `apps/api/`), Settings → Build → Dockerfile path **`workers/Dockerfile`**.
2. Variables: same `DATABASE_URL`, `REDIS_URL`, and the AI provider keys (+ `SENTRY_DSN` if used). It needs no cookie/CORS/JWT config.
3. The image's default command embeds **celery beat** (`-B`) — the hourly stale-job reaper and daily monitoring run automatically. Keep this service at **exactly 1 replica**; if you ever scale workers, remove `-B` and run a dedicated beat service (the Dockerfile comment says the same).

## 4. Vercel — web

1. Import the repo → root directory `apps/web` (Vercel detects the npm workspace).
2. Environment variable (Build): `NEXT_PUBLIC_API_URL=https://api.yourdomain.com` — **the build fails loudly if you forget it**; that's intentional.
3. Add domain `app.yourdomain.com`.

## 5. Email (password reset + verification)

Without this, reset links go to the server log (`EMAIL_BACKEND=console` logs a warning in production but doesn't block boot). To go live, on the **API** service add:

```
EMAIL_BACKEND=resend            # or smtp (SMTP_HOST/PORT/USERNAME/PASSWORD/STARTTLS)
RESEND_API_KEY=re_...
EMAIL_FROM="AI Search Growth OS <no-reply@yourdomain.com>"
```

Resend setup: add + verify your domain in Resend (two DNS records), create an API key. Note: with a real backend set, production requires `WEB_BASE_URL` to not be localhost.

## 6. Stripe (skip until you charge)

1. Dashboard → Products: create **Starter** and **Growth**, each with one monthly recurring price. Copy the two `price_...` ids.
2. Developers → Webhooks → Add endpoint: `https://api.yourdomain.com/api/v1/billing/webhook`, events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`. Copy the signing secret.
3. API service variables: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_GROWTH`. Billing turns on exactly when the secret key is set — the Settings page grows Upgrade buttons on its own.
4. Test the whole loop in **test mode** first (test keys + `stripe listen --forward-to`), including a payment failure (card `4000 0000 0000 0341`): the org should suspend — everything 404s except Settings→billing — and recover after payment is fixed.

## 7. Sentry (recommended, 10 minutes)

Create one Sentry project, set `SENTRY_DSN` on **both** the API and worker services. That's the whole integration — no DSN, no overhead.

## 8. Smoke test

```bash
API=https://api.yourdomain.com
curl -s $API/health/ready                       # {"database":"ok","redis":"ok","status":"ready"}
curl -s -D- -o /dev/null $API/health | grep -i x-request-id   # headers + request id present

# Signup → me → logout → token must be dead immediately
TOK=$(curl -s -c /tmp/cj -X POST $API/api/v1/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"you+smoke@yourdomain.com","password":"A-strong-passw0rd!","organization_name":"Smoke Co"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
curl -s -o /dev/null -w "me: %{http_code}\n"      $API/api/v1/auth/me -H "Authorization: Bearer $TOK"
curl -s -b /tmp/cj -o /dev/null -w "logout: %{http_code}\n" -X POST $API/api/v1/auth/logout
curl -s -o /dev/null -w "me after logout (want 401): %{http_code}\n" $API/api/v1/auth/me -H "Authorization: Bearer $TOK"

# Password reset email actually arrives (check the inbox, click the link)
curl -s -X POST $API/api/v1/auth/forgot-password -H 'Content-Type: application/json' \
  -d '{"email":"you+smoke@yourdomain.com"}'
```

Then in the browser: sign up fresh, create a project with a real site you own, run a crawl, run an audit, generate prompts, and (if provider keys are set) run a small prompt set — watch Settings → Plan & billing show the metered spend.

## 9. Beta onboarding checklist

- [ ] Crawl 5–10 **diverse real sites you have permission for** before inviting anyone — redirects, big sitemaps, slow servers. Watch the worker logs; stuck jobs self-heal within ~2h (QUEUED) / job-type ceiling (RUNNING) via the reaper.
- [ ] Free plan is deliberately tight (1 project, $0.50/day AI). Upgrade beta orgs by hand until Stripe is live: `UPDATE organizations SET plan='growth' WHERE slug='their-slug';`
- [ ] Replace the placeholder support address (`support@aisearchgrowth.example`) in `apps/web/src/app/(public)/privacy/page.tsx` and `terms/page.tsx`, and have counsel review both pages before charging.
- [ ] Watch Sentry + Railway logs the first week; every API log line carries a `request_id` you can grep.
- [ ] Keep `AI_DAILY_COST_LIMIT_USD` set until you trust plan budgets against real usage.

## Troubleshooting

**API won't boot, "must be set to a strong secret":** you deployed with `.env.example` placeholders — generate real values (§1). This is the guard working.
**Web shows "The API could not be reached":** wrong `NEXT_PUBLIC_API_URL` (rebuild required — it's baked at build time) or the web origin is missing from `CORS_ORIGINS`. Production never shows sample data, so this fails honestly.
**Login works, but the session drops after ~15 min:** the refresh cookie isn't coming back — setup B without `COOKIE_SAMESITE=none`, or the web origin isn't in `CORS_ORIGINS`.
**Stripe webhook 422s:** wrong `STRIPE_WEBHOOK_SECRET` (each endpoint has its own signing secret; test and live differ).
