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
}

export interface NavSection {
  /** Section heading; the unlabeled first section renders without one. */
  label?: string;
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
      { href: "/app", label: "Overview", icon: LayoutDashboardIcon, exact: true },
      { href: "/app/projects", label: "Projects", icon: FolderKanbanIcon },
    ],
  },
  {
    label: "AI Visibility",
    items: [
      { href: "/app/ai-visibility", label: "Overview", icon: EyeIcon, exact: true },
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
    items: [
      { href: "/app/geo", label: "Overview", icon: GaugeIcon, exact: true },
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
    items: [
      { href: "/app/ai-intelligence", label: "Citation Intelligence", icon: NetworkIcon, exact: true },
      { href: "/app/competitive", label: "Competitive Visibility", icon: BarChart3Icon, exact: true },
      { href: "/app/competitive/insights", label: "Insights", icon: LightbulbIcon },
      { href: "/app/competitive/discovery", label: "Discovery", icon: TelescopeIcon },
      { href: "/app/competitive/content-gaps", label: "Content Gaps", icon: PuzzleIcon },
      { href: "/app/ai-intelligence/citation-gaps", label: "Citation Gaps", icon: TargetIcon },
      { href: "/app/competitive/alerts", label: "Alerts", icon: BellIcon },
    ],
  },
  {
    label: "AI Operations",
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
