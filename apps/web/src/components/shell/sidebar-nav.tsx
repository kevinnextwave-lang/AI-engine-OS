"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS, isActive, type NavItem } from "@/components/shell/nav-items";
import { cn } from "@ai-search-growth-os/ui";

function NavLink({
  item,
  active,
  nested,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  nested?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        nested && "py-1.5 pl-9 text-[13px]",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      <item.icon className={cn("size-4", nested && "size-3.5")} aria-hidden="true" />
      {item.label}
    </Link>
  );
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Primary" className="flex flex-col gap-1 p-2">
      {NAV_ITEMS.map((item) => {
        if (!item.children) {
          return (
            <NavLink key={item.href} item={item} active={isActive(pathname, item)} onNavigate={onNavigate} />
          );
        }
        const groupActive = isActive(pathname, item);
        return (
          <div key={item.href} className="flex flex-col gap-0.5">
            <div
              className={cn(
                "flex items-center gap-3 px-3 pt-3 pb-1 text-xs font-semibold tracking-wide uppercase",
                groupActive ? "text-foreground" : "text-muted-foreground",
              )}
            >
              <item.icon className="size-4" aria-hidden="true" />
              {item.label}
            </div>
            {item.children.map((child) => (
              <NavLink
                key={child.href}
                item={child}
                nested
                active={isActive(pathname, child)}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        );
      })}
    </nav>
  );
}
