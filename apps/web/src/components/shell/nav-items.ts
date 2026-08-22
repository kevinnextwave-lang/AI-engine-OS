import {
  BrainCircuitIcon,
  BracesIcon,
  EyeIcon,
  FileTextIcon,
  LineChartIcon,
  LinkIcon,
  MessageSquareTextIcon,
  NetworkIcon,
  QuoteIcon,
  SwordsIcon,
  TargetIcon,
  BotMessageSquareIcon,
  FolderKanbanIcon,
  GaugeIcon,
  GlobeIcon,
  LayoutDashboardIcon,
  CpuIcon,
  SettingsIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** exact match only (used for overview routes so they aren't always active) */
  exact?: boolean;
  children?: NavItem[];
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/app", label: "Overview", icon: LayoutDashboardIcon, exact: true },
  { href: "/app/projects", label: "Projects", icon: FolderKanbanIcon },
  {
    href: "/app/geo",
    label: "GEO",
    icon: GaugeIcon,
    children: [
      { href: "/app/geo", label: "Overview", icon: LayoutDashboardIcon, exact: true },
      { href: "/app/geo/website-audit", label: "Website Audit", icon: GlobeIcon },
      { href: "/app/geo/technical-seo", label: "Technical SEO", icon: WrenchIcon },
      { href: "/app/geo/content", label: "Content", icon: FileTextIcon },
      { href: "/app/geo/structured-data", label: "Structured Data", icon: BracesIcon },
      { href: "/app/geo/ai-readiness", label: "AI Readiness", icon: BrainCircuitIcon },
    ],
  },
  {
    href: "/app/ai-visibility",
    label: "AI Visibility",
    icon: EyeIcon,
    children: [
      { href: "/app/ai-visibility", label: "Overview", icon: LayoutDashboardIcon, exact: true },
      { href: "/app/ai-visibility/ai-engines", label: "AI Engines", icon: CpuIcon },
      { href: "/app/ai-visibility/prompts", label: "Prompts", icon: MessageSquareTextIcon },
      { href: "/app/ai-visibility/competitors", label: "Competitors", icon: SwordsIcon },
      { href: "/app/ai-visibility/trends", label: "Trends", icon: LineChartIcon },
    ],
  },
  {
    href: "/app/ai-intelligence",
    label: "AI Intelligence",
    icon: NetworkIcon,
    children: [
      { href: "/app/ai-intelligence", label: "Overview", icon: LayoutDashboardIcon, exact: true },
      { href: "/app/ai-intelligence/ai-responses", label: "AI Responses", icon: BotMessageSquareIcon },
      { href: "/app/ai-intelligence/citations", label: "Citations", icon: LinkIcon },
      { href: "/app/ai-intelligence/sources", label: "Sources", icon: GlobeIcon },
      { href: "/app/ai-intelligence/claims", label: "Claims", icon: QuoteIcon },
      { href: "/app/ai-intelligence/citation-gaps", label: "Citation Gaps", icon: TargetIcon },
    ],
  },
  { href: "/app/settings", label: "Settings", icon: SettingsIcon },
];

export function isActive(pathname: string, item: NavItem): boolean {
  return item.exact ? pathname === item.href : pathname.startsWith(item.href);
}
