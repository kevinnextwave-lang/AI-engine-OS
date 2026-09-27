import {
  BarChart3Icon,
  BellIcon,
  BotIcon,
  BotMessageSquareIcon,
  BracesIcon,
  BrainCircuitIcon,
  ClipboardListIcon,
  CpuIcon,
  EyeIcon,
  FileEditIcon,
  FileTextIcon,
  FolderKanbanIcon,
  GaugeIcon,
  GlobeIcon,
  LayoutDashboardIcon,
  LibraryIcon,
  LightbulbIcon,
  LineChartIcon,
  LinkIcon,
  ListChecksIcon,
  ListTodoIcon,
  MessageSquareTextIcon,
  NetworkIcon,
  PuzzleIcon,
  QuoteIcon,
  RadarIcon,
  SettingsIcon,
  SwordsIcon,
  TagsIcon,
  TargetIcon,
  TelescopeIcon,
  WorkflowIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** exact match only (used for overview/hub routes so they aren't always active) */
  exact?: boolean;
  /** One-line wayfinding description (tooltip + screen-reader text). Set it
   * where the label alone is ambiguous — e.g. the three "Overview"s and the
   * two gap analyses. */
  description?: string;
}

export interface NavSection {
  /** Section heading; the unlabeled first section renders without one. */
  label?: string;
  /** One line on what this product area covers. */
  description?: string;
  items: NavItem[];
}

/**
 * Information architecture: product areas, not backend modules. Every route
 * keeps its URL — only the grouping changed — so nothing here breaks routing.
 *
 * - AI Visibility: how AI engines see the brand (measurement + the raw
 *   responses/citations/sources/claims those measurements come from).
 * - Website: everything derived from crawling your own site (the GEO module).
 * - Intelligence: derived findings — competitive standing, gaps, insights,
 *   alerts, plus the two analysis dashboards.
 * - AI Operations: agents and the human review queues they feed.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { href: "/app", label: "Overview", icon: LayoutDashboardIcon, exact: true, description: "Workspace home: your current project and top priorities." },
      { href: "/app/priorities", label: "Priorities", icon: ListTodoIcon },
      { href: "/app/projects", label: "Projects", icon: FolderKanbanIcon },
    ],
  },
  {
    label: "AI Visibility",
    description: "How AI engines see your brand — and the responses, citations and sources behind the numbers.",
    items: [
      { href: "/app/ai-visibility", label: "Overview", icon: EyeIcon, exact: true, description: "How often AI engines mention, recommend and cite your brand." },
      { href: "/app/ai-visibility/ai-engines", label: "AI Engines", icon: CpuIcon },
      { href: "/app/ai-visibility/prompts", label: "Prompts", icon: MessageSquareTextIcon },
      { href: "/app/ai-intelligence/ai-responses", label: "AI Responses", icon: BotMessageSquareIcon },
      { href: "/app/ai-intelligence/citations", label: "Citations", icon: LinkIcon },
      { href: "/app/ai-intelligence/sources", label: "Sources", icon: LibraryIcon },
      { href: "/app/ai-intelligence/claims", label: "Claims", icon: QuoteIcon },
      { href: "/app/ai-visibility/competitors", label: "Competitors", icon: SwordsIcon },
      { href: "/app/ai-visibility/trends", label: "Trends", icon: LineChartIcon },
    ],
  },
  {
    label: "Website",
    description: "Everything measured by crawling and auditing your own site.",
    items: [
      { href: "/app/geo", label: "Overview", icon: GaugeIcon, exact: true, description: "How healthy the website is for AI search, from real crawls and audits." },
      { href: "/app/geo/website-audit", label: "Website Audit", icon: GlobeIcon },
      { href: "/app/geo/crawls", label: "Crawls", icon: RadarIcon },
      { href: "/app/geo/technical-seo", label: "Technical SEO", icon: WrenchIcon },
      { href: "/app/geo/content", label: "Content", icon: FileTextIcon },
      { href: "/app/geo/structured-data", label: "Structured Data", icon: BracesIcon },
      { href: "/app/geo/ai-readiness", label: "AI Readiness", icon: BrainCircuitIcon },
    ],
  },
  {
    label: "Intelligence",
    description: "Derived findings: competitive standing, gaps, insights and alerts.",
    items: [
      { href: "/app/ai-intelligence", label: "Citation Intelligence", icon: NetworkIcon, exact: true, description: "Which sources AI answers cite, for you and for competitors." },
      { href: "/app/competitive", label: "Competitive Visibility", icon: BarChart3Icon, exact: true, description: "Your measured standing against the competitors you configured." },
      { href: "/app/competitive/insights", label: "Insights", icon: LightbulbIcon, description: "Observed patterns that coincide with competitors winning — correlations, not causation." },
      { href: "/app/competitive/discovery", label: "Discovery", icon: TelescopeIcon, description: "Competitor candidates detected in AI answers, waiting for your review." },
      { href: "/app/competitive/content-gaps", label: "Content Gaps", icon: PuzzleIcon, description: "Topics where AI answers lean on competitors while your site says little." },
      { href: "/app/ai-intelligence/citation-gaps", label: "Citation Gaps", icon: TargetIcon, description: "Sources that appear in relevant answers but rarely cite you." },
      { href: "/app/competitive/alerts", label: "Alerts", icon: BellIcon },
    ],
  },
  {
    label: "AI Operations",
    description: "Agents that propose work, and the queues where you approve it.",
    items: [
      { href: "/app/agents", label: "Agents", icon: BotIcon, exact: true },
      { href: "/app/agents/runs", label: "Runs & Approvals", icon: ListChecksIcon },
      { href: "/app/agents/workflows", label: "Workflows", icon: WorkflowIcon },
      { href: "/app/agents/briefs", label: "Content Briefs", icon: ClipboardListIcon },
      { href: "/app/agents/content-reviews", label: "Content Reviews", icon: FileEditIcon },
      { href: "/app/agents/entity-reviews", label: "Entity Reviews", icon: TagsIcon },
    ],
  },
];

/** Pinned to the bottom of the sidebar, outside the scrolling section list. */
export const SETTINGS_ITEM: NavItem = { href: "/app/settings", label: "Settings", icon: SettingsIcon };

export function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function sectionActive(pathname: string, section: NavSection): boolean {
  return section.items.some((item) => isActive(pathname, item));
}
