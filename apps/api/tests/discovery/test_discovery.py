"""AI competitor discovery (5B): extraction, aggregation, confidence, evidence,
duplicates, AI-assisted validation, acceptance/rejection, tenant isolation."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.openai import OpenAIProvider
from app.ai.registry import ProviderRegistry
from app.api.v1.routes.execution import get_provider_registry
from app.discovery.extract import extract_observations
from app.discovery.schema import AICandidateList
from app.discovery.service import Aggregate, CompetitorDiscoveryService
from app.models.competitor_candidates import CompetitorCandidate
from app.models.intelligence import BrandMention
from app.models.prompts import AiResponse, FunnelStage, PromptCategory
from tests.ai.test_providers import OPENAI_OK, json_response, transport
from tests.conftest import auth_header
from tests.execution.test_execution import settings
from tests.test_authz import signup
from tests.visibility.seed import Seeder, project_with_competitors

# --- extraction (pure) -----------------------------------------------------------------

LIST_ANSWER = """Here are the best accounting tools for startups:

1. **QuickBooks Online** — the market leader (https://quickbooks.intuit.com/online).
2. **Xero**: great for small teams.
3. **Ledgerly** – modern and well-reviewed.
4. **Wave Accounting** - has a free tier.

Popular alternatives to QuickBooks include Zoho Books, Sage Intacct and NetSuite.
Overall, the best option depends on your needs.
"""


def test_extract_observations_finds_list_items_and_alternative_language() -> None:
    obs = {o.name: o for o in extract_observations(LIST_ANSWER, frozenset({"ledgerly", "xero"}))}
    assert "Ledgerly" not in obs and "Xero" not in obs  # excluded identities
    assert obs["QuickBooks Online"].position == 1 and obs["QuickBooks Online"].domains == {
        "quickbooks.intuit.com"
    }
    assert obs["Wave Accounting"].position == 4 and not obs["Wave Accounting"].competitor_language
    assert obs["Zoho Books"].competitor_language and obs["Sage Intacct"].competitor_language
    assert "Overall" not in obs and "Here" not in obs  # generic words never become names


def test_ai_schema_is_strict() -> None:
    good = AICandidateList.model_validate_json(
        json.dumps(
            {
                "candidates": [
                    {
                        "name": "Zoho Books",
                        "domain": "WWW.Zoho.com",
                        "reason": "SMB accounting suite",
                        "confidence": 0.8,
                        "category": "accounting",
                    }
                ]
            }
        )
    )
    assert good.candidates[0].domain == "zoho.com"
    with pytest.raises(ValueError):
        AICandidateList.model_validate_json(
            json.dumps({"candidates": [{"name": "X", "reason": "r", "confidence": 2}]})
        )
    with pytest.raises(ValueError):
        AICandidateList.model_validate_json(
            json.dumps(
                {"candidates": [{"name": "Xero", "reason": "ok", "confidence": 0.5, "extra": 1}]}
            )
        )
    with pytest.raises(ValueError):
        AICandidateList.model_validate_json(
            json.dumps(
                {
                    "candidates": [
                        {"name": "Xero", "reason": "ok", "confidence": 0.5, "domain": "not a host"}
                    ]
                }
            )
        )


def test_confidence_components() -> None:
    providers = {"openai", "google", "anthropic"}
    strong = Aggregate(name="Zoho Books", normalized="zohobooks")
    for _i in range(12):
        strong.responses.add(uuid.uuid4())
    strong.prompts = {uuid.uuid4(): f"p{i}" for i in range(4)}
    strong.commercial_prompts = set(strong.prompts)
    strong.co_occurring = set(list(strong.responses)[:9])
    strong.providers = set(providers)
    strong.observations = 12
    strong.language_hits = 9
    strong.domains = {"zoho.com"}
    s = CompetitorDiscoveryService.score(strong, providers)
    assert s["label"] == "high" and s["score"] >= 0.7
    assert s["components"]["frequency"] == 1.0 and s["components"]["cross_provider"] == 1.0
    assert s["components"]["domain_confidence"] == 1.0
    weak = Aggregate(name="Acme", normalized="acme")
    weak.responses = {uuid.uuid4(), uuid.uuid4()}
    weak.prompts = {uuid.uuid4(): "p"}
    weak.providers = {"openai"}
    weak.observations = 2
    w = CompetitorDiscoveryService.score(weak, providers)
    assert w["label"] == "low" and w["components"]["competitor_language"] == 0.0
    ai_only = Aggregate(
        name="Beta",
        normalized="beta",
        ai={"confidence": 0.9, "domain": "beta.com", "provider": "openai", "reason": "r"},
    )
    a = CompetitorDiscoveryService.score(ai_only, providers)
    assert a["components"]["frequency"] == 0.0 and a["label"] == "low"


# --- discovery over the database -----------------------------------------------------------


async def _seed_answers(
    db_session: AsyncSession,
    s: Seeder,
    *,
    n: int = 6,
    providers: tuple[str, ...] = ("openai", "google"),
) -> None:
    for i in range(n):
        run = await s.observation(
            prompt=f"best accounting tools {i % 3}",
            days_ago=1 + i,
            provider=providers[i % len(providers)],
            category=PromptCategory.RECOMMENDATION,
            funnel_stage=FunnelStage.CONSIDERATION,
        )
        resp = (
            await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
        ).one()
        resp.response_text = (
            LIST_ANSWER if i % 2 == 0 else LIST_ANSWER.replace("Wave Accounting", "Bench")
        )
    # one more response naming a one-off company
    run = await s.observation(prompt="one-off", days_ago=2)
    resp = (
        await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
    ).one()
    resp.response_text = "1. **Kashoo** — a niche option.\n2. **Ledgerly** — solid."
    await db_session.commit()


def registry_with(answer: str | None) -> ProviderRegistry:
    reg = ProviderRegistry(settings())
    if answer is not None:
        body = {**OPENAI_OK, "choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
        reg.register(
            "openai",
            OpenAIProvider(
                "k", client=transport(lambda r: json_response(200, body)), default_timeout_seconds=2
            ),
        )
    return reg


AI_ANSWER = json.dumps(
    {
        "candidates": [
            {
                "name": "Zoho Books",
                "domain": "zoho.com",
                "reason": "Cloud accounting for SMBs",
                "confidence": 0.85,
                "category": "accounting",
            },
            {
                "name": "Bonsai",
                "domain": None,
                "reason": "Freelancer invoicing",
                "confidence": 0.4,
                "category": None,
            },
            {
                "name": "Xero",
                "domain": "xero.com",
                "reason": "already known",
                "confidence": 0.9,
                "category": None,
            },
        ]
    }
)


async def test_discovery_creates_evidenced_candidates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)  # Xero + QuickBooks configured
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_answers(db_session, s)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(AI_ANSWER)
    r = await client.post(f"/api/v1/projects/{pid}/competitor-candidates/discover", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["responses_scanned"] == 7 and body["ai_used"] and body["ai_error"] is None
    assert body["candidates_skipped_single_mention"] == 1  # Kashoo: one response, no other source
    items = (await client.get(f"/api/v1/projects/{pid}/competitor-candidates", headers=h)).json()[
        "items"
    ]
    by = {i["name"]: i for i in items}
    assert (
        "Kashoo" not in by
        and "Xero" not in by
        and "QuickBooks Online" not in by
        and "Ledgerly" not in by
    )
    # Zoho Books: in every list answer (6 responses, 2 engines, competitor language) + AI
    z = by["Zoho Books"]
    assert z["source"] == "combined" and z["domain"] == "zoho.com" and z["status"] == "new"
    ev = z["evidence"]
    assert (
        ev["responses"] == 6
        and ev["prompt_count"] == 3
        and set(ev["providers"]) == {"openai", "google"}
    )
    assert ev["competitor_language_hits"] == 6 and ev["co_occurring_responses"] == 6
    assert ev["ai"]["reason"] == "Cloud accounting for SMBs" and ev["confidence"]["label"] in (
        "high",
        "medium",
    )
    assert (
        "Appeared in 6 relevant AI responses" in z["reason"]
        and "suggested by openai" in z["reason"]
    )
    assert [p["text"] for p in ev["prompts"]][:1] == ["best accounting tools 0"]
    # Wave: 3 responses, one engine (openai), no competitor language → lower
    assert (
        by["Wave Accounting"]["evidence"]["responses"] == 3
        and by["Wave Accounting"]["confidence"] < z["confidence"]
    )
    assert by["Wave Accounting"]["source"] == "ai_responses"
    # Bonsai: AI only, no domain → low, source ai_assisted
    assert (
        by["Bonsai"]["source"] == "ai_assisted"
        and by["Bonsai"]["confidence_label"] == "low"
        and by["Bonsai"]["domain"] is None
    )
    assert by["Bench"]["evidence"]["responses"] == 3
    assert z["confidence"] > by["Bench"]["confidence"] > by["Bonsai"]["confidence"]


async def test_rerun_merges_duplicates_and_keeps_review_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_answers(db_session, s)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(
        None
    )  # no provider configured
    first = (
        await client.post(
            f"/api/v1/projects/{pid}/competitor-candidates/discover",
            json={"use_ai": True},
            headers=h,
        )
    ).json()
    assert first["ai_used"] is False and first["ai_error"] == "no AI provider configured"
    items = (await client.get(f"/api/v1/projects/{pid}/competitor-candidates", headers=h)).json()[
        "items"
    ]
    zoho = next(i for i in items if i["name"] == "Zoho Books")
    assert zoho["source"] == "ai_responses"
    assert (
        await client.post(f"/api/v1/competitor-candidates/{zoho['id']}/reject", headers=h)
    ).json()["status"] == "rejected"
    # second run with the AI answer: same rows (no duplicates), rejected stays rejected,
    # evidence merged
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(AI_ANSWER)
    await client.post(f"/api/v1/projects/{pid}/competitor-candidates/discover", headers=h)
    items2 = (await client.get(f"/api/v1/projects/{pid}/competitor-candidates", headers=h)).json()[
        "items"
    ]
    assert len(items2) == len(items) + 1  # only Bonsai is new
    zoho2 = next(i for i in items2 if i["name"] == "Zoho Books")
    assert (
        zoho2["id"] == zoho["id"]
        and zoho2["status"] == "rejected"
        and zoho2["source"] == "combined"
    )
    assert (
        await db_session.scalar(
            select(CompetitorCandidate.id).where(
                CompetitorCandidate.project_id == uuid.UUID(pid),
                CompetitorCandidate.normalized_name == "zohobooks",
            )
        )
        is not None
    )
    # filters
    assert (
        await client.get(
            f"/api/v1/projects/{pid}/competitor-candidates",
            params={"status": "rejected"},
            headers=h,
        )
    ).json()["total"] == 1
    assert (
        await client.get(
            f"/api/v1/projects/{pid}/competitor-candidates",
            params={"source": "ai_assisted"},
            headers=h,
        )
    ).json()["items"][0]["name"] == "Bonsai"


async def test_invalid_ai_json_is_discarded(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_answers(db_session, s, n=2)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(
        '{"candidates": [{"name": "Evil", "confidence": 9}]}'
    )
    body = (
        await client.post(f"/api/v1/projects/{pid}/competitor-candidates/discover", headers=h)
    ).json()
    assert body["ai_used"] and "failed validation" in body["ai_error"]
    names = {
        i["name"]
        for i in (
            await client.get(f"/api/v1/projects/{pid}/competitor-candidates", headers=h)
        ).json()["items"]
    }
    assert "Evil" not in names
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(
        "Sure! Here are some ideas: Zoho, Sage."
    )
    body = (
        await client.post(f"/api/v1/projects/{pid}/competitor-candidates/discover", headers=h)
    ).json()
    assert body["ai_error"] == "AI answer contained no JSON object"


async def test_accept_and_reject(client: AsyncClient, db_session: AsyncSession) -> None:
    h, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    await _seed_answers(db_session, s)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(AI_ANSWER)
    await client.post(f"/api/v1/projects/{pid}/competitor-candidates/discover", headers=h)
    items = {
        i["name"]: i
        for i in (
            await client.get(f"/api/v1/projects/{pid}/competitor-candidates", headers=h)
        ).json()["items"]
    }
    before = len((await client.get(f"/api/v1/projects/{pid}/competitors", headers=h)).json())
    # accept with a known domain → competitor created with discovered source and
    # evidence-based description
    r = await client.post(
        f"/api/v1/competitor-candidates/{items['Zoho Books']['id']}/accept", headers=h
    )
    assert r.status_code == 200, r.text
    comp = r.json()
    assert (
        comp["name"] == "Zoho Books"
        and comp["domain"] == "zoho.com"
        and comp["source"] == "discovered"
    )
    assert (
        comp["confidence"] == items["Zoho Books"]["confidence_label"]
        and "Appeared in 6" in comp["description"]
    )
    cand = (
        await client.get(f"/api/v1/competitor-candidates/{items['Zoho Books']['id']}", headers=h)
    ).json()
    assert (
        cand["status"] == "accepted" and cand["competitor_id"] == comp["id"] and cand["reviewed_at"]
    )
    assert (
        await client.post(
            f"/api/v1/competitor-candidates/{items['Zoho Books']['id']}/accept", headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitor-candidates/{items['Zoho Books']['id']}/reject", headers=h
        )
    ).status_code == 409
    # accept without a domain requires a website_url
    assert (
        await client.post(
            f"/api/v1/competitor-candidates/{items['Bonsai']['id']}/accept", headers=h
        )
    ).status_code == 422
    r = await client.post(
        f"/api/v1/competitor-candidates/{items['Bonsai']['id']}/accept",
        json={"website_url": "hellobonsai.com", "name": "Bonsai"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["domain"] == "hellobonsai.com"
    # duplicate of an existing competitor is refused by the competitor service
    r = await client.post(
        f"/api/v1/competitor-candidates/{items['Wave Accounting']['id']}/accept",
        json={"website_url": "zoho.com"},
        headers=h,
    )
    assert r.status_code == 409
    assert (
        len((await client.get(f"/api/v1/projects/{pid}/competitors", headers=h)).json())
        == before + 2
    )
    r = await client.post(f"/api/v1/competitor-candidates/{items['Bench']['id']}/reject", headers=h)
    assert (
        r.status_code == 200
        and r.json()["status"] == "rejected"
        and r.json()["reviewed_by_user_id"]
    )
    # once accepted, the name is a known competitor: re-discovery no longer lists it
    await client.post(f"/api/v1/projects/{pid}/competitor-candidates/discover", headers=h)
    items2 = {
        i["name"]: i
        for i in (
            await client.get(f"/api/v1/projects/{pid}/competitor-candidates", headers=h)
        ).json()["items"]
    }
    assert items2["Zoho Books"]["status"] == "accepted" and items2["Bench"]["status"] == "rejected"


async def test_tenant_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h_a, _, pid_a = await project_with_competitors(client)
    h_b, _, pid_b = await project_with_competitors(client)
    sa_ = Seeder(db_session, uuid.UUID(pid_a))
    await _seed_answers(db_session, sa_)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: registry_with(None)
    await client.post(f"/api/v1/projects/{pid_a}/competitor-candidates/discover", headers=h_a)
    a = (await client.get(f"/api/v1/projects/{pid_a}/competitor-candidates", headers=h_a)).json()
    assert a["total"] >= 3
    cid = a["items"][0]["id"]
    assert (
        await client.get(f"/api/v1/projects/{pid_a}/competitor-candidates", headers=h_b)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid_a}/competitor-candidates/discover", headers=h_b)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/competitor-candidates/{cid}", headers=h_b)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/competitor-candidates/{cid}/accept", headers=h_b)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/competitor-candidates/{cid}/reject", headers=h_b)
    ).status_code == 404
    assert (await client.get(f"/api/v1/competitor-candidates/{cid}")).status_code == 401
    # B's own discovery sees nothing of A
    assert (
        await client.post(f"/api/v1/projects/{pid_b}/competitor-candidates/discover", headers=h_b)
    ).json()["candidates_written"] == 0
    assert (
        await client.get(f"/api/v1/projects/{pid_b}/competitor-candidates", headers=h_b)
    ).json()["total"] == 0
    stranger = await signup(client, org="Stranger")
    assert (
        await client.get(
            f"/api/v1/competitor-candidates/{cid}", headers=auth_header(stranger["access_token"])
        )
    ).status_code == 404
    assert BrandMention is not None  # (import used by seeding module)
