"""Pure-function tests: validation, extraction, sameAs classification, consistency."""

import uuid

from app.crawler.intelligence import analyze_page
from app.crawler.urls import normalize_crawl_url
from app.entities.consistency import find_inconsistencies
from app.entities.extraction import extract_entities, make_fingerprint, normalize_name
from app.entities.same_as import classify, is_authoritative
from app.entities.validation import validate_block
from app.models.entities import Entity, EntityScope
from app.models.page_intelligence import StructuredDataFormat as F

ORG = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Acme Inc.",
    "url": "https://www.acme.com/",
    "foundingDate": "2018",
    "sameAs": ["https://www.linkedin.com/company/acme", "https://en.wikipedia.org/wiki/Acme"],
    "address": {"@type": "PostalAddress", "addressLocality": "Paris"},
}


def _codes(issues):  # type: ignore[no-untyped-def]
    return [i.code for i in issues]


# --- validation ---------------------------------------------------------------


def test_valid_jsonld_has_no_issues() -> None:
    assert validate_block(F.JSON_LD, ORG, True, None) == []


def test_malformed_jsonld_from_crawler_error() -> None:
    issues = validate_block(F.JSON_LD, None, False, "invalid JSON: Expecting ',' delimiter")
    assert _codes(issues) == ["invalid_json"] and issues[0].severity == "high"


def test_missing_context_and_type_and_invalid_nesting() -> None:
    doc = {"name": "x", "author": {"name": "y"}, "keywords": [["a"]], "image": ""}
    codes = _codes(validate_block(F.JSON_LD, doc, True, None))
    assert "missing_context" in codes and "missing_type" in codes
    assert "invalid_nested_structure" in codes and "empty_value" in codes
    assert _codes(validate_block(F.JSON_LD, "just a string", True, None)) == ["invalid_root"]
    assert _codes(
        validate_block(F.JSON_LD, {"@context": "https://schema.org", "@type": ""}, True, None)
    ) == ["invalid_type_value"]
    assert _codes(
        validate_block(F.JSON_LD, {"@context": "https://schema.org", "@graph": {}}, True, None)
    ) == ["invalid_graph"]


def test_graph_wrapper_needs_no_type_but_members_do() -> None:
    doc = {
        "@context": "https://schema.org",
        "@graph": [{"@type": "WebSite", "name": "A"}, {"name": "B"}],
    }
    issues = validate_block(F.JSON_LD, doc, True, None)
    assert [(i.code, i.path) for i in issues] == [("missing_type", "@graph[1]")]


def test_non_schema_context_is_informational() -> None:
    doc = {"@context": "https://example.org/vocab", "@type": "Thing", "name": "x"}
    issues = validate_block(F.JSON_LD, doc, True, None)
    assert _codes(issues) == ["non_schema_org_context"] and issues[0].severity == "info"


# --- extraction ---------------------------------------------------------------


def test_extracts_nested_and_graph_entities() -> None:
    doc = {
        "@context": "https://schema.org",
        "@graph": [
            ORG,
            {
                "@type": ["BlogPosting", "Article"],
                "headline": "Hello world",
                "author": {"@type": "Person", "name": "Jane Doe"},
                "publisher": {"@id": "https://www.acme.com/#org"},
            },
        ],
    }
    entities = {e.json_path: e for e in extract_entities(doc)}
    assert set(entities) == {"@graph[0]", "@graph[0].address", "@graph[1]", "@graph[1].author"}
    org = entities["@graph[0]"]
    assert org.entity_type == "Organization" and org.name == "Acme Inc." and org.is_known_type
    assert org.same_as == ORG["sameAs"] and org.properties["foundingDate"] == "2018"
    assert org.properties["address"] == {"@ref": True, "@type": "PostalAddress"}
    assert org.fingerprint == "Organization|acme"
    post = entities["@graph[1]"]
    assert post.entity_type == "BlogPosting" and post.extra_types == ["Article"]
    assert post.name == "Hello world"
    assert post.properties["author"]["name"] == "Jane Doe"
    assert entities["@graph[1].author"].fingerprint == "Person|jane doe"
    assert not entities["@graph[0].address"].is_known_type


def test_multiple_schemas_on_one_page_become_separate_blocks() -> None:
    html = (
        b'<html><head><script type="application/ld+json">'
        b'{"@context":"https://schema.org","@type":"WebSite","name":"Acme"}</script>'
        b'<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage",'
        b'"mainEntity":[{"@type":"Question","name":"Q?","acceptedAnswer":{"@type":"Answer","text":"A"}}]}'
        b'</script><script type="application/ld+json">{not json</script></head>'
        b'<body><div itemscope itemtype="https://schema.org/Product"><span itemprop="name">W</span>'
        b'<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        b'<meta itemprop="price" content="9.99"></div></div></body></html>'
    )
    intel = analyze_page(
        html, normalize_crawl_url("https://www.acme.com/"), allowed_hosts=frozenset()
    )
    blocks = intel.structured_data
    assert [(b.format, b.is_valid) for b in blocks] == [
        ("json_ld", True),
        ("json_ld", True),
        ("json_ld", False),
        ("microdata", True),
    ]
    assert blocks[2].error.startswith("invalid JSON")  # type: ignore[union-attr]
    faq = extract_entities(blocks[1].payload)
    assert [e.entity_type for e in faq] == ["Answer", "Question", "FAQPage"]
    product = extract_entities(blocks[3].payload)
    assert [(e.entity_type, e.name) for e in product] == [("Offer", None), ("Product", "W")]
    assert product[0].properties == {"price": "9.99"}


def test_identifiers_and_property_values() -> None:
    doc = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Widget",
        "sku": "W-1",
        "identifier": {"@type": "PropertyValue", "propertyID": "asin", "value": "B000"},
    }
    product = next(e for e in extract_entities(doc) if e.entity_type == "Product")
    assert sorted(product.identifier) == ["asin:B000", "sku:W-1"]


def test_name_normalization() -> None:
    assert normalize_name("ACME, Inc.") == "acme"
    assert normalize_name("Café Société") == "cafe societe"
    assert make_fingerprint("Organization", "  ") is None


# --- sameAs -------------------------------------------------------------------


def test_same_as_classification() -> None:
    assert classify("https://www.linkedin.com/company/acme") == "linkedin"
    assert classify("https://fr.wikipedia.org/wiki/Acme") == "wikipedia"
    assert classify("https://www.wikidata.org/wiki/Q42") == "wikidata"
    assert classify("https://twitter.com/acme") == "x" and classify("https://x.com/acme") == "x"
    assert classify("https://acme.example/") == "other"
    assert is_authoritative("wikidata") and not is_authoritative("facebook")


# --- consistency --------------------------------------------------------------


def _entity(page_id: uuid.UUID, path: str = "", **props) -> Entity:  # type: ignore[no-untyped-def]
    return Entity(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        page_id=page_id,
        scope=EntityScope.PAGE,
        source_format=F.JSON_LD,
        entity_type="Organization",
        extra_types=[],
        name="Acme",
        url=props.pop("url", "https://www.acme.com/"),
        same_as=props.pop("same_as", []),
        identifier=[],
        properties=props,
        json_path=path,
        fingerprint="Organization|acme",
    )


def test_contradictory_values_across_pages_are_reported_not_resolved() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    urls = {
        a: "https://www.acme.com/",
        b: "https://www.acme.com/about",
        c: "https://www.acme.com/x",
    }
    obs = find_inconsistencies(
        [
            _entity(a, foundingDate="2018", telephone="+33 1 00 00 00 00"),
            _entity(b, foundingDate="2019", telephone="+33 1 00 00 00 00"),
            _entity(c, foundingDate="2018"),
        ],
        urls,
    )
    assert [o.code for o in obs] == ["entity_value_conflict"]
    o = obs[0]
    assert o.title == "Potential factual inconsistency" and o.severity == "medium"
    assert o.evidence["property"] == "foundingDate"
    assert {v["value"]: sorted(v["pages"]) for v in o.evidence["values"]} == {
        "2018": [urls[a], urls[c]],
        "2019": [urls[b]],
    }


def test_same_as_differences_are_informational_and_case_is_ignored() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    urls = {a: "https://www.acme.com/", b: "https://www.acme.com/about"}
    obs = find_inconsistencies(
        [
            _entity(a, same_as=["https://x.com/acme"], slogan="We Make Things"),
            _entity(
                b,
                same_as=["https://x.com/acme", "https://linkedin.com/company/acme"],
                slogan="we make  things",
            ),
        ],
        urls,
    )
    assert [(o.code, o.severity) for o in obs] == [("same_as_inconsistent", "info")]


def test_duplicate_entities_on_one_page() -> None:
    a = uuid.uuid4()
    obs = find_inconsistencies(
        [_entity(a, ""), _entity(a, "@graph[3]")], {a: "https://www.acme.com/"}
    )
    assert [o.code for o in obs] == ["duplicate_entity"]
    assert obs[0].evidence["count"] == 2 and obs[0].evidence["page_url"] == "https://www.acme.com/"
