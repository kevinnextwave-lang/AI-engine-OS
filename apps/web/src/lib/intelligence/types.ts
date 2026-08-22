/**
 * View models for the Citation Intelligence section. Derived from API
 * contract types by ./mappers.ts; components only render them.
 * Every number is a count of observed AI-response citations — nothing here
 * is a claim about how AI engines weigh a source.
 */

import type {
  CitationGap,
  CitationListItem,
  DomainType,
  GapConfidence,
  GapPriority,
  GapStatus,
  GapType,
  GraphEdge,
  GraphNode,
} from "@ai-search-growth-os/types";

export type { DataSource } from "@/lib/geo/types";
export type { CitationGap, CitationListItem, DomainType, GapConfidence, GapPriority, GapStatus, GapType };

export interface IntelligenceMetric {
  key: "citations" | "sources" | "brand_rate" | "competitor_rate" | "gaps";
  label: string;
  value: number | null;
  unit: "count" | "percent";
  note: string;
}

export interface TopSourceBar {
  sourceDomainId: string;
  domain: string;
  sourceType: DomainType;
  citations: number;
  brandCitations: number;
  competitorCitations: number;
}

export interface OpportunityCard {
  gap: CitationGap;
  priorityLabel: string;
  /** [name, citations] sorted desc, competitors first then brand row. */
  rows: { name: string; citations: number; isBrand: boolean }[];
}

export interface SourceRow {
  sourceDomainId: string;
  domain: string;
  displayName: string;
  sourceType: DomainType;
  citations: number;
  responses: number;
  prompts: number;
  brandCitations: number;
  competitorCitations: number;
  competitors: Record<string, number>;
  firstCitedAt: string | null;
  lastCitedAt: string | null;
  topPages: { url: string; citations: number }[];
  /** Joined from citation gaps when one exists for this source. */
  opportunity: number | null;
  gap: CitationGap | null;
}

export interface ClaimRow {
  key: string;
  subject: string;
  predicate: string;
  object: string;
  occurrences: number;
  responses: number;
  prompts: number;
  confidence: number;
  associatedWith: "brand" | "competitor" | "other";
  entityName: string | null;
  example: string | null;
  lastSeenAt: string | null;
}

export interface CitationRow {
  id: string;
  url: string | null;
  domain: string | null;
  sourceDomainId: string | null;
  sourceType: DomainType | null;
  citedAt: string | null;
  prompt: string;
  promptId: string;
  runId: string;
  provider: string | null;
  providerLabel: string;
  model: string | null;
  relationships: { name: string; relationship: string; confidence: number }[];
}

export interface SourceDetail {
  row: SourceRow;
  pages: { url: string; citations: number }[];
  engines: { provider: string; label: string; model: string | null; citations: number }[];
  brands: { name: string; citations: number }[];
  competitors: { name: string; citations: number }[];
  /** Weekly citation counts, oldest first. */
  trend: { weekStart: string; citations: number }[];
  prompts: { promptId: string; prompt: string; citations: number }[];
  citationsLoaded: number;
  citationsTotal: number;
}

export interface GraphFilters {
  competitor: string | null;
  sourceType: string | null;
  provider: string | null;
  window: "30d" | "90d" | "180d";
}

export interface GraphView {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}
