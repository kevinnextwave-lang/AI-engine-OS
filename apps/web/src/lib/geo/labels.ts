import type { ReadinessCategory, SeoCategory, Severity } from "@ai-search-growth-os/types";

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

export const SEO_CATEGORY_LABEL: Record<SeoCategory, string> = {
  indexability: "Indexability",
  metadata: "Metadata",
  headings: "Headings",
  canonicalization: "Canonicalization",
  internal_links: "Internal Links",
  http: "HTTP",
  structured_data: "Structured Data",
  mobile_html: "Mobile & HTML",
};

export const READINESS_CATEGORY_LABEL: Record<ReadinessCategory, string> = {
  entity_clarity: "Entity Clarity",
  product_clarity: "Product Clarity",
  evidence: "Evidence",
  authority: "Authority",
  content_structure: "Content Structure",
  faq: "FAQ Coverage",
  comparison: "Comparison Content",
  factual_consistency: "Factual Consistency",
};

/** Plain-language meaning of each readiness category, with no ranking claims. */
export const READINESS_CATEGORY_EXPLANATION: Record<ReadinessCategory, string> = {
  entity_clarity:
    "Whether the site states who the company is: name, description, offering, audience, geography and contact details, in text and in Organization schema.",
  product_clarity:
    "Whether product and service pages name the offering and describe features, pricing, use cases, target customers and integrations.",
  evidence:
    "Presence of statistics, research references, first-party data, citations, outbound sources, case studies and customer evidence — citation-readiness signals.",
  authority:
    "Whether articles identify their author, organization, credentials and dates, so content can be attributed.",
  content_structure:
    "How specific and structured the content is: share of sentences with concrete facts, thin pages, and long pages without headings.",
  faq: "Whether explicit question-and-answer content exists and is marked up with FAQPage schema.",
  comparison:
    "Presence of comparison-style pages (vs, alternatives, best, pricing). Recorded for information only; not scored.",
  factual_consistency:
    "Whether the same entity states the same facts across pages in its structured data.",
};

export function categoryLabel(categoryKey: string): string {
  return (
    (SEO_CATEGORY_LABEL as Record<string, string>)[categoryKey] ??
    (READINESS_CATEGORY_LABEL as Record<string, string>)[categoryKey] ??
    categoryKey.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export const STATUS_LABEL = { open: "Open", ignored: "Ignored", resolved: "Resolved" } as const;
