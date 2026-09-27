"""Per-plan product limits — the single table both enforcement and the
billing UI read.

Crawler page/depth/rate limits live in app/crawler/limits.py (they predate
this table and are already enforced there); this table adds the knobs that
gate spend and scale. None means unlimited. Prices live in Stripe, never
here — the webhook maps Stripe price IDs onto OrganizationPlan.
"""

from dataclasses import dataclass

from app.models.organization import OrganizationPlan


@dataclass(frozen=True)
class PlanLimits:
    projects_per_org: int | None
    prompts_per_batch: int
    # USD per organization per UTC day, enforced against AiUsageRecord
    # metering before a batch is accepted. The global AI_DAILY_COST_LIMIT_USD
    # setting remains an operator ceiling on top (the lower one wins).
    ai_daily_cost_usd: float
    seo_audits_per_month: int | None
    label: str


PLAN_LIMITS: dict[OrganizationPlan, PlanLimits] = {
    OrganizationPlan.FREE: PlanLimits(
        projects_per_org=1,
        prompts_per_batch=25,
        ai_daily_cost_usd=0.50,
        seo_audits_per_month=4,
        label="Free",
    ),
    OrganizationPlan.STARTER: PlanLimits(
        projects_per_org=3,
        prompts_per_batch=150,
        ai_daily_cost_usd=5.0,
        seo_audits_per_month=20,
        label="Starter",
    ),
    OrganizationPlan.GROWTH: PlanLimits(
        projects_per_org=10,
        prompts_per_batch=500,
        ai_daily_cost_usd=20.0,
        seo_audits_per_month=None,
        label="Growth",
    ),
    # Not self-serve yet; generous so a manual upgrade never fights limits.
    OrganizationPlan.PRO: PlanLimits(
        projects_per_org=25,
        prompts_per_batch=1000,
        ai_daily_cost_usd=50.0,
        seo_audits_per_month=None,
        label="Pro",
    ),
    OrganizationPlan.AGENCY: PlanLimits(
        projects_per_org=100,
        prompts_per_batch=2000,
        ai_daily_cost_usd=150.0,
        seo_audits_per_month=None,
        label="Agency",
    ),
    OrganizationPlan.ENTERPRISE: PlanLimits(
        projects_per_org=None,
        prompts_per_batch=5000,
        ai_daily_cost_usd=500.0,
        seo_audits_per_month=None,
        label="Enterprise",
    ),
}


def limits_for(plan: OrganizationPlan) -> PlanLimits:
    return PLAN_LIMITS[plan]
