/**
 * MOCK DATA — used only when no project is selected or the API is unreachable.
 * Every dataset here is returned with `source: "mock"` so the UI can label it.
 * Shapes mirror the API contract types exactly so the same mappers apply.
 */

import type {
  AiReadinessAuditDetail,
  CrawlJob,
  EntityConsistencyResponse,
  EntityListResponse,
  ProjectSchemaResponse,
  SeoAudit,
  SeoObservation,
} from "@ai-search-growth-os/types";

const MOCK_PROJECT_ID = "00000000-0000-4000-8000-00000000mock";
const ROOT = "https://www.example-mock.com/";
const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

export const MOCK_CRAWL_JOBS: CrawlJob[] = [
  {
    id: "mock-crawl-1",
    project_id: MOCK_PROJECT_ID,
    root_url: ROOT,
    status: "completed",
    crawl_type: "full",
    max_pages: 500,
    max_depth: 5,
    pages_discovered: 212,
    pages_crawled: 184,
    pages_failed: 6,
    pages_skipped: 22,
    duration_seconds: 412,
    error_message: null,
    started_at: hoursAgo(5.2),
    completed_at: hoursAgo(5),
    created_at: hoursAgo(5.3),
    updated_at: hoursAgo(5),
  },
];

export const MOCK_SEO_AUDIT: SeoAudit = {
  id: "mock-seo-audit-1",
  project_id: MOCK_PROJECT_ID,
  crawl_job_id: "mock-crawl-1",
  status: "completed",
  pages_analyzed: 184,
  observation_count: 9,
  health_score: 71.5,
  score_breakdown: { method: "technical-seo-health-score/v1" },
  summary: { by_severity: { high: 3, medium: 3, low: 2, info: 1 }, html_pages: 178, indexable_pages: 160 },
  error_message: null,
  started_at: hoursAgo(4.8),
  completed_at: hoursAgo(4.7),
  created_at: hoursAgo(4.8),
  updated_at: hoursAgo(4.7),
};

const seoBase = {
  audit_id: MOCK_SEO_AUDIT.id,
  project_id: MOCK_PROJECT_ID,
  status: "open" as const,
  status_note: null,
  status_changed_by_user_id: null,
  created_at: hoursAgo(4.7),
  updated_at: hoursAgo(4.7),
};

export const MOCK_SEO_OBSERVATIONS: SeoObservation[] = [
  {
    ...seoBase,
    id: "mock-seo-1",
    page_id: null,
    url: null,
    category: "structured_data",
    code: "structured_data_missing",
    severity: "high",
    title: "Pages without structured data",
    description:
      "12 indexable page(s) declare no JSON-LD, Microdata or RDFa. Structured data helps engines and AI systems identify the entities on a page.",
    evidence: {
      urls: [`${ROOT}`, `${ROOT}about`, `${ROOT}products/widget`, `${ROOT}products/gadget`],
      count: 12,
    },
    recommendation:
      "Add JSON-LD for the page's main entity (Organization or WebSite on the homepage; Article, Product, Service, FAQPage, etc. elsewhere).",
  },
  {
    ...seoBase,
    id: "mock-seo-2",
    page_id: null,
    url: null,
    category: "metadata",
    code: "title_duplicate",
    severity: "medium",
    title: "Multiple pages share the same title",
    description: "4 indexable pages use the title 'Products – Example'. Identical titles make it hard for engines to tell the pages apart.",
    evidence: { title: "Products – Example", urls: [`${ROOT}products`, `${ROOT}products?page=2`, `${ROOT}products?page=3`, `${ROOT}products?page=4`], count: 4 },
    recommendation:
      "Create unique titles that clearly describe the primary topic and entity represented by each page; if the pages are truly duplicates, canonicalize them to one URL instead.",
  },
  {
    ...seoBase,
    id: "mock-seo-3",
    page_id: "mock-page-3",
    url: `${ROOT}blog/launch`,
    category: "metadata",
    code: "title_missing",
    severity: "high",
    title: "Page has no title tag",
    description: "The page does not declare a <title>. Search and AI engines use the title as the primary label for the page in results and citations.",
    evidence: { http_status: 200, indexable: true },
    recommendation: "Add a <title> that names the page's primary topic and the brand, e.g. '<Topic> – <Brand>'. Keep it specific to this page.",
  },
  {
    ...seoBase,
    id: "mock-seo-4",
    page_id: null,
    url: null,
    category: "internal_links",
    code: "orphan_pages",
    severity: "medium",
    title: "Pages with no internal links pointing at them",
    description: "3 crawled page(s) are reachable only via the sitemap or a redirect, not from any other page. Engines treat such pages as unimportant.",
    evidence: { urls: [`${ROOT}legacy/offer`, `${ROOT}events/2023`, `${ROOT}press/old-release`], count: 3 },
    recommendation: "Link to these pages from relevant content, navigation, or hub pages; if they are obsolete, remove them from the sitemap.",
  },
  {
    ...seoBase,
    id: "mock-seo-5",
    page_id: "mock-page-5",
    url: `${ROOT}products/widget`,
    category: "internal_links",
    code: "broken_internal_links",
    severity: "high",
    title: "Page links to broken internal URLs",
    description: "2 internal link(s) on this page point to URLs that returned 4xx/5xx.",
    evidence: { links: [{ href: "/docs/old", anchor: "Documentation", status: 404 }, { href: "/pricing-2022", anchor: "Pricing", status: 404 }], count: 2 },
    recommendation: "Update or remove these links. If the targets were moved, redirect the old URLs to the new ones.",
  },
  {
    ...seoBase,
    id: "mock-seo-6",
    page_id: null,
    url: null,
    category: "http",
    code: "redirect_chain",
    severity: "medium",
    title: "Redirect chains",
    description: "2 URL(s) reach their destination only after 2+ redirects. Each hop adds latency and can lose ranking signals.",
    evidence: { chains: [{ from: `${ROOT}old-home`, hops: [`${ROOT}old-home`, `${ROOT}home`] }, { from: `http://example-mock.com/`, hops: ["http://example-mock.com/", "https://example-mock.com/"] }], count: 2 },
    recommendation: "Update the source links to point directly at the final URL and collapse the intermediate redirects into a single hop.",
  },
  {
    ...seoBase,
    id: "mock-seo-7",
    page_id: "mock-page-7",
    url: `${ROOT}about`,
    category: "headings",
    code: "h1_missing",
    severity: "low",
    title: "Page has no H1",
    description: "No <h1> element was found. The H1 is the strongest on-page signal of the page's main topic for both search engines and AI summarizers.",
    evidence: { h1_count: 0 },
    recommendation: "Add a single <h1> that states the page's main subject; it usually mirrors the title without being identical.",
  },
  {
    ...seoBase,
    id: "mock-seo-8",
    page_id: null,
    url: null,
    category: "mobile_html",
    code: "lang_missing",
    severity: "low",
    title: "Pages without a lang attribute",
    description: "7 page(s) do not declare <html lang>. Language detection then falls back to heuristics.",
    evidence: { urls: [`${ROOT}blog/launch`, `${ROOT}blog/roadmap`], count: 7 },
    recommendation: 'Set <html lang="xx"> (BCP 47 code) in the template, per language version.',
    status: "resolved",
    status_note: "Template fixed in release 4.2",
  },
  {
    ...seoBase,
    id: "mock-seo-9",
    page_id: null,
    url: null,
    category: "indexability",
    code: "robots_txt_missing",
    severity: "info",
    title: "No robots.txt",
    description: "The site has no robots.txt, so every path is crawlable by default.",
    evidence: {},
    recommendation: "Optional: add a robots.txt that lists your sitemap and excludes private paths (admin, search results, cart).",
  },
];

export const MOCK_SCHEMA: ProjectSchemaResponse = {
  summary: {
    pages_crawled: 178,
    pages_with_structured_data: 96,
    pages_without_structured_data: 82,
    blocks_total: 131,
    blocks_invalid: 3,
    formats: { json_ld: 118, microdata: 13 },
    schema_types: { WebPage: 90, BreadcrumbList: 84, Article: 31, Organization: 6, Product: 9, FAQPage: 2, Person: 14 },
    entity_types: { WebPage: 90, BreadcrumbList: 84, Article: 31, Organization: 6, Product: 9, Person: 14, FAQPage: 2, Question: 16, Answer: 16, PostalAddress: 2 },
    known_types_present: ["Article", "BreadcrumbList", "FAQPage", "Organization", "Person", "Product", "WebPage"],
    known_types_absent: ["AggregateRating", "BlogPosting", "Event", "LocalBusiness", "Offer", "Review", "Service", "WebSite"],
    issues_by_code: { invalid_json: 3, missing_context: 5, missing_type: 4, empty_value: 11 },
  },
  issues: [
    { id: "mock-issue-1", page_id: "mock-page-10", page_url: `${ROOT}blog/roadmap`, structured_data_id: null, format: "json_ld", block_position: 0, code: "invalid_json", severity: "high", message: "json_ld block could not be parsed: invalid JSON: Expecting ',' delimiter", json_path: "" },
    { id: "mock-issue-2", page_id: "mock-page-11", page_url: `${ROOT}products/gadget`, structured_data_id: null, format: "json_ld", block_position: 1, code: "missing_context", severity: "medium", message: "Node has no @context (schema.org vocabulary)", json_path: "" },
    { id: "mock-issue-3", page_id: "mock-page-11", page_url: `${ROOT}products/gadget`, structured_data_id: null, format: "json_ld", block_position: 1, code: "missing_type", severity: "medium", message: "Object has properties but no @type", json_path: "offers" },
  ],
  analyzed_at: hoursAgo(4.6),
  note: "Validation covers JSON-LD/Microdata/RDFa structure only. It does not assess search-engine rich-result eligibility.",
};

const entityBase = { project_id: MOCK_PROJECT_ID, extra_types: [], identifier: [], json_path: "", is_known_type: true, created_at: hoursAgo(4.6), source_format: "json_ld" as const };

export const MOCK_ENTITIES: EntityListResponse = {
  items: [
    { ...entityBase, id: "mock-ent-1", page_id: "mock-page-1", page_url: ROOT, scope: "page", entity_type: "Organization", name: "Example Mock Ltd", description: "Mock company.", url: ROOT, same_as: ["https://www.linkedin.com/company/example-mock", "https://www.wikidata.org/wiki/Q0"], properties: { foundingDate: "2016" }, links: [{ url: "https://www.linkedin.com/company/example-mock", platform: "linkedin", is_authoritative: false }, { url: "https://www.wikidata.org/wiki/Q0", platform: "wikidata", is_authoritative: true }] },
    { ...entityBase, id: "mock-ent-2", page_id: "mock-page-2", page_url: `${ROOT}about`, scope: "page", entity_type: "Organization", name: "Example Mock", description: null, url: ROOT, same_as: ["https://www.linkedin.com/company/example-mock"], properties: { foundingDate: "2017" }, links: [{ url: "https://www.linkedin.com/company/example-mock", platform: "linkedin", is_authoritative: false }] },
    { ...entityBase, id: "mock-ent-3", page_id: "mock-page-12", page_url: `${ROOT}products/widget`, scope: "page", entity_type: "Product", name: "Widget", description: "Reporting widget.", url: `${ROOT}products/widget`, same_as: [], properties: { offers: { "@ref": true, "@type": "Offer" } }, links: [] },
    { ...entityBase, id: "mock-ent-4", page_id: "mock-page-13", page_url: `${ROOT}blog/launch`, scope: "page", entity_type: "Person", name: "Jane Doe", description: null, url: null, same_as: ["https://www.linkedin.com/in/jane-doe"], properties: { jobTitle: "Head of Product" }, links: [{ url: "https://www.linkedin.com/in/jane-doe", platform: "linkedin", is_authoritative: false }] },
  ],
  total: 4,
  limit: 200,
  offset: 0,
  organization: { ...entityBase, id: "mock-ent-org", page_id: null, page_url: null, scope: "project", entity_type: "Organization", name: "Example Mock Ltd", description: "Mock company.", url: ROOT, same_as: ["https://www.linkedin.com/company/example-mock", "https://www.wikidata.org/wiki/Q0"], properties: { foundingDate: "2016", _confidence: "high", _conflicts: { foundingDate: [{ value: "2016", page_url: ROOT }, { value: "2017", page_url: `${ROOT}about` }] } }, links: [{ url: "https://www.linkedin.com/company/example-mock", platform: "linkedin", is_authoritative: false }, { url: "https://www.wikidata.org/wiki/Q0", platform: "wikidata", is_authoritative: true }] },
  analyzed_at: hoursAgo(4.6),
};

export const MOCK_CONSISTENCY: EntityConsistencyResponse = {
  items: [
    { id: "mock-cons-1", code: "entity_value_conflict", severity: "medium", title: "Potential factual inconsistency", description: "Organization 'Example Mock' states different values for 'foundingDate' on different pages (2 variants). One of them may be outdated; verify which is correct and use it everywhere.", entity_type: "Organization", entity_name: "Example Mock", evidence: { property: "foundingDate", values: [{ value: "2016", pages: [ROOT] }, { value: "2017", pages: [`${ROOT}about`] }], pages_compared: 2 }, created_at: hoursAgo(4.6) },
  ],
  total: 1,
  entities_compared: 4,
  analyzed_at: hoursAgo(4.6),
  note: "Inconsistencies list every observed value with its source pages; no value is assumed to be the correct one.",
};

const rd = (applicable: boolean, weight: number, value: number | null, how: string) => ({ applicable, weight, value, how });

export const MOCK_READINESS: AiReadinessAuditDetail = {
  id: "mock-readiness-1",
  project_id: MOCK_PROJECT_ID,
  status: "completed",
  pages_analyzed: 178,
  observation_count: 6,
  readiness_score: 64.2,
  score_breakdown: {
    method: "ai-readiness-score/v1",
    weights: { entity_clarity: 25, product_clarity: 20, authority: 15, evidence: 15, content_structure: 15, faq: 5, factual_consistency: 5 },
    applicable_weight: 100,
    categories: {
      entity_clarity: rd(true, 25, 0.833, "5 of 6 entity signals present"),
      product_clarity: rd(true, 20, 0.571, "mean aspect coverage over 9 page(s)"),
      authority: rd(true, 15, 0.5, "mean aspect coverage over 31 page(s)"),
      evidence: rd(true, 15, 0.571, "4 of 7 evidence kinds detected"),
      content_structure: rd(true, 15, 0.62, "0.6 × specificity (0.21/0.3) + 0.2 × (1 − thin share) + 0.2 × (1 − unstructured share)"),
      faq: rd(true, 5, 1, "0.5 for FAQ content, 0.5 for FAQPage schema"),
      factual_consistency: rd(true, 5, 0.75, "1 − conflicts/entities compared (1/4)"),
      comparison: rd(false, 0, null, "informational only; presence of comparison pages is recorded, not scored"),
    },
    note: "Internal product metric built only from the signals listed here. Not an industry standard; does not measure or predict AI visibility or rankings.",
  },
  summary: { page_kinds: { home: 1, product: 9, article: 31, about: 1, faq: 2, comparison: 3 }, organization_entity: true, entities_compared: 4 },
  error_message: null,
  started_at: hoursAgo(4.5),
  completed_at: hoursAgo(4.4),
  created_at: hoursAgo(4.5),
  updated_at: hoursAgo(4.4),
  observations_total: 6,
  note: "AI Readiness Score is an internal product metric computed only from the listed signals. It is not an industry standard and does not measure or predict AI visibility.",
  observations: [
    { id: "mock-rd-1", page_id: null, url: null, category: "entity_clarity", code: "entity_geographic_coverage_unclear", severity: "low", title: "Geographic coverage is not stated", description: "No address, `areaServed`, or phrase such as 'based in', 'serving', or 'worldwide' was found on the homepage, About or Contact pages.", evidence: { schema: false, examples: [] }, recommendation: "State where the company is based and which regions it serves, in text and in the Organization schema (`address`, `areaServed`)." },
    { id: "mock-rd-2", page_id: null, url: null, category: "product_clarity", code: "product_target_customers_unclear", severity: "medium", title: "Product pages do not clearly identify the target customer", description: "6 of 9 product/service page(s): No phrase naming the intended customer (e.g. 'built for agencies', 'for developers').", evidence: { urls: [`${ROOT}products/widget`, `${ROOT}products/gadget`, `${ROOT}products/gizmo`], count: 6, share: 0.67 }, recommendation: 'Add an explicit "Who it\'s for" section describing the primary customer segments and use cases.' },
    { id: "mock-rd-3", page_id: null, url: null, category: "authority", code: "article_author_missing", severity: "medium", title: "Articles without an identifiable author", description: "18 of 31 article page(s) lack this signal. Author identity, credentials and dates are citation-readiness signals that help readers and AI systems attribute content.", evidence: { urls: [`${ROOT}blog/launch`, `${ROOT}blog/roadmap`], count: 18, share: 0.58 }, recommendation: "Name the author in a byline and in Article schema `author` (a Person with `name`)." },
    { id: "mock-rd-4", page_id: null, url: null, category: "evidence", code: "evidence_original_data_absent", severity: "info", title: "No original data or first-party research found", description: "None of 140 content page(s) contains this kind of evidence (lexical detection).", evidence: { content_pages: 140 }, recommendation: "Publish findings from your own data (benchmarks, surveys) — a strong citation-readiness signal." },
    { id: "mock-rd-5", page_id: null, url: null, category: "content_structure", code: "content_specificity_low", severity: "low", title: "Pages with few specific statements", description: "14 page(s) of 300+ words have under 10% of sentences containing a number, date, product or organization name. Generic text gives AI systems and readers little to cite.", evidence: { pages: [{ url: `${ROOT}blog/culture`, specific_ratio: 0.04, sentences: 52 }, { url: `${ROOT}about`, specific_ratio: 0.07, sentences: 30 }], count: 14 }, recommendation: "Replace vague claims with specifics: named products, numbers, dates, locations and the organizations involved." },
    { id: "mock-rd-6", page_id: null, url: null, category: "factual_consistency", code: "entity_facts_inconsistent", severity: "low", title: "Entity facts differ between pages", description: "1 property value conflict(s) were found between structured-data declarations of the same entity (see entity consistency).", evidence: { conflicts: [{ entity_type: "Organization", entity_name: "Example Mock", property: "foundingDate", values: ["2016", "2017"] }], count: 1 }, recommendation: "Decide the correct value for each property listed and use it on every page." },
  ],
};
