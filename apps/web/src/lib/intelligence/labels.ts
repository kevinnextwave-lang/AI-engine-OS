import type { DomainType, GapConfidence, GapStatus, GapType } from "@ai-search-growth-os/types";

export const SOURCE_TYPE_LABEL: Record<DomainType, string> = {
  company: "Company site",
  media: "Media",
  review: "Review site",
  community: "Community",
  directory: "Directory",
  government: "Government",
  education: "Education",
  social: "Social",
  forum: "Forum",
  blog: "Blog",
  research: "Research",
  other: "Other",
  unknown: "Unknown",
};

export const GAP_TYPE_LABEL: Record<GapType, string> = {
  brand_absent: "Brand absent",
  competitor_advantage: "Competitor advantage",
  source_underrepresented: "Underrepresented",
  source_overrepresented: "Brand dominates",
  shared_source: "Shared source",
  emerging_source: "Emerging source",
};

export const GAP_STATUS_LABEL: Record<GapStatus, string> = {
  new: "New",
  reviewing: "Reviewing",
  accepted: "Accepted",
  dismissed: "Dismissed",
  in_progress: "In progress",
  completed: "Completed",
};

export const CONFIDENCE_LABEL: Record<GapConfidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
  insufficient: "Not enough data",
};

export const PRIORITY_LABEL = { high: "High opportunity", medium: "Medium opportunity", low: "Low opportunity" } as const;

/**
 * Neutral, non-manipulative guidance per gap type. Deliberately never suggests
 * buying reviews, link schemes, or any form of manipulation, and never implies
 * that a citation guarantees AI visibility.
 */
export const RECOMMENDATION: Record<GapType, string> = {
  brand_absent:
    "Investigate whether this source is relevant to your market and whether legitimate editorial, review, partnership, research, or community opportunities exist. Being present on a source that AI engines already consult makes it possible to be cited there; it does not guarantee it.",
  competitor_advantage:
    "Competitors are already represented here. Review how they appear (product listings, reviews, comparisons, contributed content) and whether an equally legitimate presence is available to you — for example a verified listing, participation in a comparison, or a contributed article where the source accepts them.",
  source_underrepresented:
    "Neither you nor your competitors are clearly represented on this source yet. Check whether it is genuinely relevant to your category before investing; if it is, look for legitimate ways to be covered (editorial pitches, community participation, data or research contributions).",
  source_overrepresented:
    "You already dominate this source. No action needed beyond keeping the information there accurate and current.",
  shared_source:
    "You and your competitors are cited here at similar rates. Keep your presence accurate and complete; consider whether the pages cited about you are the ones you would choose.",
  emerging_source:
    "This source has started to appear recently. Watch whether it keeps growing before committing effort, and check its relevance and credibility for your market.",
};

export const RECOMMENDATION_DISCLAIMER =
  "These are starting points for investigation, not instructions. Do not pursue paid placements disguised as editorial, fake reviews, link schemes, or other manipulation — they violate most sources' policies and can harm your brand.";
