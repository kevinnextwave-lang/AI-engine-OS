"""Competitor intelligence data model (5A): CRUD, aliases, domains, products,
duplicate handling, authorization."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitors.normalize import normalize_name
from app.core.security import create_access_token
from app.models import MembershipRole
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("QuickBooks", "quickbooks"),
        ("Quick Books, Inc.", "quickbooks"),
        ("QUICKBOOKS LLC", "quickbooks"),
        ("Zoho Books Ltd", "zohobooks"),
        ("Café Inc", "cafe"),
        ("Co", "co"),  # a lone suffix is still a name
        ("!!!", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


async def _project(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    owner = await signup(client, org="Comp Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (
        await create_project(client, h, name="Ledgerly", website_url="https://www.ledgerly.example")
    )["id"]
    return h, org, pid


async def test_competitor_crud(client: AsyncClient) -> None:
    h, _, pid = await _project(client)
    r = await client.post(
        f"/api/v1/projects/{pid}/competitors",
        json={
            "name": "QuickBooks",
            "website_url": "quickbooks.intuit.com",
            "description": "Intuit's SMB accounting suite",
            "aliases": ["QBO", "QuickBooks Online"],
            "confidence": "high",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert (
        c["domain"] == "quickbooks.intuit.com" and c["normalized_domain"] == "quickbooks.intuit.com"
    )
    assert c["hostname"] == c["domain"] and c["website_url"] == "https://quickbooks.intuit.com"
    assert c["source"] == "manual" and c["status"] == "active" and c["confidence"] == "high"
    assert [a["alias"] for a in c["aliases"]] == ["QBO", "QuickBooks Online"]
    assert c["domains"][0]["domain"] == "quickbooks.intuit.com" and c["domains"][0]["is_primary"]
    assert c["domains"][0]["domain_type"] == "primary" and c["products"] == []
    cid = c["id"]

    got = (await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()
    assert got["id"] == cid and got["description"] == "Intuit's SMB accounting suite"

    r = await client.patch(
        f"/api/v1/competitors/{cid}",
        json={
            "name": "QuickBooks Online",
            "status": "ignored",
            "confidence": "medium",
            "description": None,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    u = r.json()
    assert (
        u["name"] == "QuickBooks Online"
        and u["status"] == "ignored"
        and u["confidence"] == "medium"
    )
    assert u["description"] is None
    # changing the website moves the primary domain
    u = (
        await client.patch(
            f"/api/v1/competitors/{cid}",
            json={"website_url": "https://www.qbo.example/"},
            headers=h,
        )
    ).json()
    assert u["domain"] == "www.qbo.example" and u["normalized_domain"] == "qbo.example"
    assert [d["domain"] for d in u["domains"] if d["is_primary"]] == ["qbo.example"]

    listed = (await client.get(f"/api/v1/projects/{pid}/competitors", headers=h)).json()
    assert [x["id"] for x in listed] == [cid]
    assert (
        await client.get(
            f"/api/v1/projects/{pid}/competitors", params={"status": "active"}, headers=h
        )
    ).json() == []
    assert (
        len(
            (
                await client.get(
                    f"/api/v1/projects/{pid}/competitors", params={"status": "ignored"}, headers=h
                )
            ).json()
        )
        == 1
    )

    assert (await client.delete(f"/api/v1/competitors/{cid}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/competitors/{cid}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/competitors", headers=h)).json() == []
    # validation
    assert (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": " ", "website_url": "x.com"},
            headers=h,
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "Bad", "website_url": "ftp://x.com"},
            headers=h,
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "Bad", "website_url": "x.com", "source": "magic"},
            headers=h,
        )
    ).status_code == 422


async def test_duplicate_handling(client: AsyncClient) -> None:
    h, _, pid = await _project(client)
    base = f"/api/v1/projects/{pid}/competitors"
    first = await client.post(
        base,
        json={"name": "Xero", "website_url": "https://www.xero.com", "aliases": ["Xero Ltd"]},
        headers=h,
    )
    assert first.status_code == 201
    cid = first.json()["id"]
    cases = [
        (
            {"name": "Xero Accounting", "website_url": "xero.com"},
            "already tracked as Xero",
        ),  # same domain (www stripped)
        (
            {"name": "XERO, Inc.", "website_url": "https://other.example"},
            "already identifies competitor Xero",
        ),  # same normalised name
        (
            {"name": "Xero Ltd", "website_url": "https://another.example"},
            "already identifies competitor Xero",
        ),  # alias collision
        (
            {"name": "Me", "website_url": "https://ledgerly.example/about"},
            "own domains",
        ),  # the project's own site
    ]
    for body, message in cases:
        r = await client.post(base, json=body, headers=h)
        assert r.status_code == 409, (body, r.text)
        assert message in r.json()["error"]["message"]
    # a second competitor, then renaming it onto the first is rejected
    second = (
        await client.post(base, json={"name": "Sage", "website_url": "https://sage.com"}, headers=h)
    ).json()
    assert (
        await client.patch(f"/api/v1/competitors/{second['id']}", json={"name": "xero"}, headers=h)
    ).status_code == 409
    assert (
        await client.patch(
            f"/api/v1/competitors/{second['id']}", json={"website_url": "xero.com"}, headers=h
        )
    ).status_code == 409
    # a product of one competitor cannot be added as another competitor
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/products", json={"name": "Xero Payroll"}, headers=h
        )
    ).status_code == 201
    assert (
        await client.post(
            base, json={"name": "Xero Payroll", "website_url": "https://payroll.example"}, headers=h
        )
    ).status_code == 409
    assert len((await client.get(base, headers=h)).json()) == 2


async def test_aliases(client: AsyncClient) -> None:
    h, _, pid = await _project(client)
    cid = (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "FreshBooks", "website_url": "freshbooks.com"},
            headers=h,
        )
    ).json()["id"]
    other = (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "Wave", "website_url": "waveapps.com"},
            headers=h,
        )
    ).json()["id"]
    for alias in ("Fresh Books", "FB Invoicing", "FreshBooks Cloud Accounting"):
        r = await client.post(
            f"/api/v1/competitors/{cid}/aliases", json={"alias": alias}, headers=h
        )
        assert r.status_code == 201, r.text
    c = (await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()
    assert [a["normalized_alias"] for a in c["aliases"]] == [
        "freshbooks",
        "fbinvoicing",
        "freshbookscloudaccounting",
    ]
    # duplicates: same alias again, the competitor's own name, another competitor's name
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/aliases", json={"alias": "fresh books"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/aliases", json={"alias": "FreshBooks"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/competitors/{cid}/aliases", json={"alias": "Wave"}, headers=h)
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitors/{other}/aliases", json={"alias": "FB Invoicing"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/competitors/{cid}/aliases", json={"alias": "??"}, headers=h)
    ).status_code == 422
    alias_id = c["aliases"][1]["id"]
    assert (
        await client.delete(f"/api/v1/competitors/{cid}/aliases/{alias_id}", headers=h)
    ).status_code == 200
    assert (
        await client.delete(f"/api/v1/competitors/{cid}/aliases/{alias_id}", headers=h)
    ).status_code == 404
    assert len((await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()["aliases"]) == 2


async def test_domains(client: AsyncClient) -> None:
    h, _, pid = await _project(client)
    cid = (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "Zoho Books", "website_url": "https://www.zoho.com/books"},
            headers=h,
        )
    ).json()["id"]
    other = (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "Sage", "website_url": "sage.com"},
            headers=h,
        )
    ).json()["id"]
    r = await client.post(
        f"/api/v1/competitors/{cid}/domains",
        json={"domain": "help.zoho.com", "domain_type": "support"},
        headers=h,
    )
    assert (
        r.status_code == 201
        and r.json()["domain"] == "help.zoho.com"
        and not r.json()["is_primary"]
    )
    r = await client.post(
        f"/api/v1/competitors/{cid}/domains",
        json={"domain": "WWW.Zohobooks.example.", "domain_type": "product", "is_primary": True},
        headers=h,
    )
    assert (
        r.status_code == 201
        and r.json()["domain"] == "zohobooks.example"
        and r.json()["is_primary"]
    )
    c = (await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()
    assert [d["is_primary"] for d in c["domains"]] == [False, False, True]  # primary moved
    assert {d["domain_type"] for d in c["domains"]} == {"primary", "support", "product"}
    # duplicates and invalid
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/domains", json={"domain": "help.zoho.com"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitors/{other}/domains", json={"domain": "zoho.com"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/domains", json={"domain": "ledgerly.example"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/domains", json={"domain": "not a host"}, headers=h
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/domains",
            json={"domain": "x.com", "domain_type": "cdn"},
            headers=h,
        )
    ).status_code == 422
    primary = next(d for d in c["domains"] if d["is_primary"])
    support = next(d for d in c["domains"] if d["domain_type"] == "support")
    assert (
        await client.delete(f"/api/v1/competitors/{cid}/domains/{primary['id']}", headers=h)
    ).status_code == 409
    assert (
        await client.delete(f"/api/v1/competitors/{cid}/domains/{support['id']}", headers=h)
    ).status_code == 200
    assert len((await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()["domains"]) == 2


async def test_products(client: AsyncClient) -> None:
    h, _, pid = await _project(client)
    cid = (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "Intuit", "website_url": "intuit.com"},
            headers=h,
        )
    ).json()["id"]
    r = await client.post(
        f"/api/v1/competitors/{cid}/products",
        json={
            "name": "QuickBooks Online",
            "description": "Cloud accounting",
            "url": "quickbooks.intuit.com/online",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert (
        p["url"] == "https://quickbooks.intuit.com/online"
        and p["description"] == "Cloud accounting"
    )
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/products", json={"name": "quickbooks-online"}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/competitors/{cid}/products", json={"name": "Bad", "url": "ftp://x"}, headers=h
        )
    ).status_code == 422
    r = await client.patch(
        f"/api/v1/competitors/{cid}/products/{p['id']}",
        json={"name": "QuickBooks Online Advanced", "url": ""},
        headers=h,
    )
    assert (
        r.status_code == 200
        and r.json()["name"] == "QuickBooks Online Advanced"
        and r.json()["url"] is None
    )
    assert (
        await client.patch(
            f"/api/v1/competitors/{cid}/products/{uuid.uuid4()}", json={"name": "x"}, headers=h
        )
    ).status_code == 404
    c = (await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()
    assert [x["name"] for x in c["products"]] == ["QuickBooks Online Advanced"]
    assert (
        await client.delete(f"/api/v1/competitors/{cid}/products/{p['id']}", headers=h)
    ).status_code == 200
    assert (await client.get(f"/api/v1/competitors/{cid}", headers=h)).json()["products"] == []


async def test_authorization_and_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h_a, org_a, pid_a = await _project(client)
    h_b, _, pid_b = await _project(client)
    cid = (
        await client.post(
            f"/api/v1/projects/{pid_a}/competitors",
            json={"name": "Xero", "website_url": "xero.com", "aliases": ["Xero Ltd"]},
            headers=h_a,
        )
    ).json()["id"]
    c = (await client.get(f"/api/v1/competitors/{cid}", headers=h_a)).json()
    alias_id, domain_id = c["aliases"][0]["id"], c["domains"][0]["id"]
    # tenant B: same competitor name/domain is allowed in its own project, nothing of A is reachable
    assert (
        await client.post(
            f"/api/v1/projects/{pid_b}/competitors",
            json={"name": "Xero", "website_url": "xero.com"},
            headers=h_b,
        )
    ).status_code == 201
    for method, path, body in (
        ("GET", f"/api/v1/competitors/{cid}", None),
        ("PATCH", f"/api/v1/competitors/{cid}", {"name": "Hacked"}),
        ("DELETE", f"/api/v1/competitors/{cid}", None),
        ("POST", f"/api/v1/competitors/{cid}/aliases", {"alias": "X"}),
        ("DELETE", f"/api/v1/competitors/{cid}/aliases/{alias_id}", None),
        ("POST", f"/api/v1/competitors/{cid}/domains", {"domain": "x.com"}),
        ("DELETE", f"/api/v1/competitors/{cid}/domains/{domain_id}", None),
        ("POST", f"/api/v1/competitors/{cid}/products", {"name": "X"}),
        ("GET", f"/api/v1/projects/{pid_a}/competitors", None),
        ("POST", f"/api/v1/projects/{pid_a}/competitors", {"name": "Y", "website_url": "y.com"}),
    ):
        r = await client.request(method, path, json=body, headers=h_b)
        assert r.status_code == 404, (method, path, r.status_code)
        assert (await client.request(method, path, json=body)).status_code == 401
    # nothing changed in A
    c2 = (await client.get(f"/api/v1/competitors/{cid}", headers=h_a)).json()
    assert c2["name"] == "Xero" and len(c2["aliases"]) == 1 and len(c2["domains"]) == 1
    # viewer in A's org: read yes, write no (403)
    viewer = await add_member(db_session, org_a, "viewer-comp@example.com", MembershipRole.VIEWER)
    await db_session.commit()
    hv = auth_header(create_access_token(str(viewer)))
    assert (await client.get(f"/api/v1/competitors/{cid}", headers=hv)).status_code == 200
    assert (
        await client.get(f"/api/v1/projects/{pid_a}/competitors", headers=hv)
    ).status_code == 200
    assert (
        await client.patch(f"/api/v1/competitors/{cid}", json={"name": "Z"}, headers=hv)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/competitors/{cid}/aliases", json={"alias": "Z"}, headers=hv)
    ).status_code == 403
    assert (await client.delete(f"/api/v1/competitors/{cid}", headers=hv)).status_code == 403
    # deleting a competitor cascades its aliases/domains/products
    assert (await client.delete(f"/api/v1/competitors/{cid}", headers=h_a)).status_code == 200
    assert (await client.get(f"/api/v1/competitors/{cid}", headers=h_a)).status_code == 404
