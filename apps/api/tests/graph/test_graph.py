"""AI Search Graph (4D): the six graph questions, overview bounds, organization isolation."""

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.queries import GraphQueryService, Window
from app.models.intelligence import CompetitorMention, ResponseCitation, ResponseClaim
from app.models.prompts import AiResponse
from app.sources.service import SourceIntelligenceService
from tests.conftest import auth_header
from tests.test_authz import signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

PV = "response-parser/v1"
WINDOW = Window(NOW - timedelta(days=90), NOW)


async def _seed_graph(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[dict[str, str], str, Seeder]:
    """8 prompts × a few responses: g2 cites competitors a lot, capterra cites only
    QuickBooks, the brand site cites the brand, reddit cites nobody; claims repeat;
    one source (trustpilot) only appears in the second half of the window."""
    h, _, pid = await project_with_competitors(client)  # QuickBooks, Xero
    s = Seeder(db_session, uuid.UUID(pid))
    svc = SourceIntelligenceService(db_session)
    hosts = await svc.project_hosts(s.project_id)
    assert hosts
    for i in range(40):
        prompt = f"prompt {i % 8}"
        days = 1 + (i * 2) % 80
        urls = [
            "https://www.g2.com/products/quickbooks/reviews"
            if i % 2
            else "https://www.g2.com/products/xero/reviews",
        ]
        if i % 4 == 0:
            urls.append("https://www.capterra.com/p/1/QuickBooks/")
        if i % 5 == 0:
            urls.append("https://www.ledgerly.example/pricing")
        if i % 8 == 0:
            urls.append("https://www.reddit.com/r/smallbusiness/x")
        if i % 3 == 0 and days <= 30:
            urls.append("https://www.trustpilot.com/review/quickbooks.com")
        run = await s.observation(prompt=prompt, days_ago=days, mentioned=i % 3 != 0, position=2)
        resp = (
            await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
        ).one()
        for url in urls:
            c = ResponseCitation(
                ai_response_id=resp.id,
                project_id=s.project_id,
                url=url,
                domain=None,
                citation_type="explicit_url",
                parser_version=PV,
            )
            db_session.add(c)
            await db_session.flush()
            c.created_at = NOW - timedelta(days=days)
            await db_session.flush()
            await svc.resolve_citation(c, hosts)
        if i % 2 == 0:
            db_session.add(
                CompetitorMention(
                    ai_response_id=resp.id,
                    project_id=s.project_id,
                    competitor_name="QuickBooks",
                    mention_text="QuickBooks",
                    position=1,
                    sentiment="positive",
                    recommendation_strength="strong",
                    parser_version=PV,
                )
            )
        if i % 4 == 0:
            db_session.add(
                CompetitorMention(
                    ai_response_id=resp.id,
                    project_id=s.project_id,
                    competitor_name="Xero",
                    mention_text="Xero",
                    position=3,
                    sentiment="neutral",
                    recommendation_strength="weak",
                    parser_version=PV,
                )
            )
        if i % 2 == 0:
            db_session.add(
                ResponseClaim(
                    ai_response_id=resp.id,
                    project_id=s.project_id,
                    subject="QuickBooks",
                    predicate="offers",
                    object="payroll add-on",
                    confidence=0.8,
                    context="QuickBooks offers a payroll add-on.",
                    parser_version=PV,
                )
            )
        if i % 5 == 0:
            db_session.add(
                ResponseClaim(
                    ai_response_id=resp.id,
                    project_id=s.project_id,
                    subject="Ledgerly",
                    predicate="offers",
                    object="Stripe sync",
                    confidence=0.7,
                    context="Ledgerly offers Stripe sync.",
                    parser_version=PV,
                )
            )
        if i == 7:
            db_session.add(
                ResponseClaim(
                    ai_response_id=resp.id,
                    project_id=s.project_id,
                    subject="Wave",
                    predicate="is",
                    object="free",
                    confidence=0.5,
                    context="Wave is free.",
                    parser_version=PV,
                )
            )
    await db_session.commit()
    return h, pid, s


async def test_q1_most_cited_sources(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, _ = await _seed_graph(client, db_session)
    body = (await client.get(f"/api/v1/projects/{pid}/graph/sources", headers=h)).json()
    assert body["view"] == "top" and body["limit"] == 50
    domains = [i["domain"] for i in body["items"]]
    assert domains[0] == "g2.com" and body["items"][0]["citations"] == 40
    assert body["items"][0]["competitors"] == {"QuickBooks": 20, "Xero": 20}
    assert body["items"][0]["top_pages"][0]["citations"] == 20
    assert set(domains) == {
        "g2.com",
        "capterra.com",
        "ledgerly.example",
        "reddit.com",
        "trustpilot.com",
    }
    assert body["total"] == 5
    # filters and pagination
    r = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/sources",
            params={"source_type": "review", "limit": 2},
            headers=h,
        )
    ).json()
    assert [i["domain"] for i in r["items"]] == ["g2.com", "capterra.com"] and r["total"] == 3
    r2 = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/sources",
            params={"source_type": "review", "limit": 2, "offset": 2},
            headers=h,
        )
    ).json()
    assert [i["domain"] for i in r2["items"]] == ["trustpilot.com"]


async def test_q2_q3_competitor_and_gap_sources(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, _ = await _seed_graph(client, db_session)
    comp = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/sources", params={"view": "competitor"}, headers=h
        )
    ).json()
    assert [i["domain"] for i in comp["items"]] == ["g2.com", "capterra.com", "trustpilot.com"]
    assert comp["items"][0]["competitor_share"] == 1.0
    gap = (
        await client.get(f"/api/v1/projects/{pid}/graph/sources", params={"view": "gap"}, headers=h)
    ).json()
    assert [i["domain"] for i in gap["items"]] == ["g2.com", "capterra.com", "trustpilot.com"]
    assert all(i["brand_citations"] == 0 and i["brand_ratio"] == 0.0 for i in gap["items"])
    assert "ledgerly.example" not in [i["domain"] for i in gap["items"]]


async def test_q5_rising_sources(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, s = await _seed_graph(client, db_session)
    # compare last 45 days to the 45 before: trustpilot only exists in the recent half
    w = Window(NOW - timedelta(days=45), NOW)
    items, total = await GraphQueryService(db_session).sources(s.project_id, w, view="rising")
    by = {i["domain"]: i for i in items}
    assert "trustpilot.com" in by and by["trustpilot.com"]["previous_citations"] == 0
    assert by["trustpilot.com"]["growth"] >= by.get("g2.com", {"growth": -1})["growth"]
    assert total == len(items) and all(i["growth"] > 0 for i in items)
    r = await client.get(
        f"/api/v1/projects/{pid}/graph/sources",
        params={"view": "rising", "start": w.start.isoformat(), "end": w.end.isoformat()},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["items"][0]["domain"] == "trustpilot.com"


async def test_q4_prompts_by_competitor_citations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, _ = await _seed_graph(client, db_session)
    body = (await client.get(f"/api/v1/projects/{pid}/graph/prompts", headers=h)).json()
    assert body["total"] == 8 and len(body["items"]) == 8
    first = body["items"][0]
    assert first["competitor_citations"] >= body["items"][-1]["competitor_citations"]
    assert first["responses"] == 5 and first["citations"] >= 5
    assert set(first["competitors"]) <= {"QuickBooks", "Xero"}
    g2 = next(t for t in first["top_sources"] if t["domain"] == "g2.com")
    assert g2["citations"] == 5 == first["top_sources"][0]["citations"]  # ties allowed
    assert sum(i["brand_mentions"] for i in body["items"]) == 26  # 40 − 14 unmentioned (i % 3 == 0)
    assert sum(i["competitor_mentions"] for i in body["items"]) == 30  # 20 QuickBooks + 10 Xero
    page = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/prompts", params={"limit": 3, "offset": 6}, headers=h
        )
    ).json()
    assert len(page["items"]) == 2 and page["total"] == 8


async def test_q6_repeated_claims(client: AsyncClient, db_session: AsyncSession) -> None:
    h, pid, _ = await _seed_graph(client, db_session)
    body = (await client.get(f"/api/v1/projects/{pid}/graph/claims", headers=h)).json()
    assert body["total"] == 2  # "Wave is free" appears once → below min_occurrences
    qb = body["items"][0]
    assert (
        qb["subject"] == "quickbooks"
        and qb["occurrences"] == 20
        and qb["associated_with"] == "competitor"
    )
    assert qb["entity_name"] == "QuickBooks" and qb["responses"] == 20 and qb["prompts"] == 4
    assert qb["examples"] == ["QuickBooks offers a payroll add-on."]
    brand = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/claims", params={"associated_with": "brand"}, headers=h
        )
    ).json()
    assert [i["object"] for i in brand["items"]] == ["stripe sync"] and brand["items"][0][
        "occurrences"
    ] == 8
    other = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/claims",
            params={"associated_with": "other", "min_occurrences": 1},
            headers=h,
        )
    ).json()
    assert [i["subject"] for i in other["items"]] == ["wave"]


async def test_competitors_and_competes_with_edges(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, _ = await _seed_graph(client, db_session)
    body = (await client.get(f"/api/v1/projects/{pid}/graph/competitors", headers=h)).json()
    by = {i["name"]: i for i in body["items"]}
    assert (
        by["Ledgerly"]["is_brand"]
        and by["Ledgerly"]["mentions"] == 26
        and by["Ledgerly"]["citations"] == 8
    )
    assert by["QuickBooks"]["mentions"] == 20 and by["QuickBooks"]["citations"] == 20 + 10 + 5
    assert by["QuickBooks"]["competitor_id"] and by["Xero"]["mentions"] == 10
    assert by["QuickBooks"]["top_sources"][0]["domain"] == "g2.com"
    assert by["QuickBooks"]["co_mentions_with_brand"] > 0
    edges = {
        e["target"].split(":")[0] + ":" + str(by[n]["competitor_id"])
        for n in ("QuickBooks", "Xero")
        for e in body["edges"]
        if e["target"].endswith(str(by[n]["competitor_id"]))
    }
    assert len(edges) == 2 and all(
        e["type"] == "competes_with" and e["weight"] > 0 for e in body["edges"]
    )


async def test_overview_is_bounded_and_consistent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, pid, _ = await _seed_graph(client, db_session)
    body = (await client.get(f"/api/v1/projects/{pid}/graph/overview", headers=h)).json()
    types = {n["type"] for n in body["nodes"]}
    assert types == {"project", "brand", "competitor", "prompt", "source_domain", "claim"}
    edge_types = {e["type"] for e in body["edges"]}
    assert {
        "tracks",
        "has_prompt",
        "mentions",
        "cites",
        "associated_with",
        "competes_with",
        "claims",
    } <= edge_types
    st = body["statistics"]
    assert st["responses"] == 40 and st["prompts"] == 8 and st["models"] == 1
    assert st["brand_mentions"] == 26 and st["competitor_mentions"] == 30 and st["claims"] == 29
    assert (
        st["citations"] == 40 + 10 + 8 + 5 + 5
        and st["source_domains"] == 5
        and st["source_pages"] == 6
    )
    assert st["competitors_configured"] == 2 and not st["truncated"]
    assert st["nodes_returned"] == len(body["nodes"]) and st["edges_returned"] == len(body["edges"])
    ids = {n["id"] for n in body["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in body["edges"])
    # top-N bounds and truncation flag
    small = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/overview",
            params={"top_sources": 2, "top_prompts": 3, "top_claims": 0},
            headers=h,
        )
    ).json()
    assert sum(1 for n in small["nodes"] if n["type"] == "source_domain") == 2
    assert sum(1 for n in small["nodes"] if n["type"] == "prompt") == 3
    assert (
        not any(n["type"] == "claim" for n in small["nodes"]) and small["statistics"]["truncated"]
    )
    # date filter: an empty window yields an empty graph, not an error
    empty = (
        await client.get(
            f"/api/v1/projects/{pid}/graph/overview",
            params={"start": "2020-01-01T00:00:00Z", "end": "2020-02-01T00:00:00Z"},
            headers=h,
        )
    ).json()
    assert empty["statistics"]["responses"] == 0 and [n["type"] for n in empty["nodes"]] == [
        "project",
        "brand",
        "competitor",
        "competitor",
    ]
    assert (
        await client.get(
            f"/api/v1/projects/{pid}/graph/overview",
            params={"start": "2026-02-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
            headers=h,
        )
    ).status_code == 422


async def test_organization_isolation(client: AsyncClient, db_session: AsyncSession) -> None:
    h_a, pid_a, _ = await _seed_graph(client, db_session)
    h_b, pid_b, _ = await _seed_graph(client, db_session)
    for path in ("overview", "sources", "competitors", "prompts", "claims"):
        assert (
            await client.get(f"/api/v1/projects/{pid_a}/graph/{path}", headers=h_b)
        ).status_code == 404
        assert (await client.get(f"/api/v1/projects/{pid_a}/graph/{path}")).status_code == 401
        assert (
            await client.get(f"/api/v1/projects/{pid_a}/graph/{path}", headers=h_a)
        ).status_code == 200
    # both tenants cite the same shared source rows, but each graph only counts its own citations
    a = (await client.get(f"/api/v1/projects/{pid_a}/graph/sources", headers=h_a)).json()["items"][
        0
    ]
    b = (await client.get(f"/api/v1/projects/{pid_b}/graph/sources", headers=h_b)).json()["items"][
        0
    ]
    assert a["source_domain_id"] == b["source_domain_id"] and a["citations"] == b["citations"] == 40
    ov = (await client.get(f"/api/v1/projects/{pid_a}/graph/overview", headers=h_a)).json()
    assert ov["statistics"]["responses"] == 40 and ov["project_id"] == pid_a
    stranger = await signup(client, org="Stranger")
    assert (
        await client.get(
            f"/api/v1/projects/{pid_a}/graph/overview",
            headers=auth_header(stranger["access_token"]),
        )
    ).status_code == 404
