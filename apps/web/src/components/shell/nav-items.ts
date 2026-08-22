import { FolderKanbanIcon, LayoutDashboardIcon, SettingsIcon, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** exact match only (used for the overview route so it isn't always active) */
  exact?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/app", label: "Overview", icon: LayoutDashboardIcon, exact: true },
  { href: "/app/projects", label: "Projects", icon: FolderKanbanIcon },
  { href: "/app/settings", label: "Settings", icon: SettingsIcon },
];

export function isActive(pathname: string, item: NavItem): boolean {
  return item.exact ? pathname === item.href : pathname.startsWith(item.href);
}
