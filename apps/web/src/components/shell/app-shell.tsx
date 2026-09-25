"use client";

import { MenuIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { isActive, SETTINGS_ITEM } from "@/components/shell/nav-items";
import { OrganizationSwitcher } from "@/components/shell/organization-switcher";
import { NavLink, SidebarNav } from "@/components/shell/sidebar-nav";
import { UserMenu } from "@/components/shell/user-menu";
import {
  Button,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@ai-search-growth-os/ui";

function Brand() {
  return (
    <Link href="/app" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
      <span className="bg-primary text-primary-foreground flex size-7 items-center justify-center rounded-md text-xs">
        AI
      </span>
      <span>Search Growth OS</span>
    </Link>
  );
}

/** Sidebar body shared between the desktop rail and the mobile sheet. */
function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      <div className="shrink-0 px-3 pt-3 pb-2">
        <OrganizationSwitcher variant="sidebar" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <SidebarNav onNavigate={onNavigate} />
      </div>
      <div className="shrink-0 border-t px-3 py-2">
        <NavLink item={SETTINGS_ITEM} active={isActive(pathname, SETTINGS_ITEM)} onNavigate={onNavigate} />
      </div>
    </>
  );
}

/**
 * Reusable application shell: persistent sidebar on ≥md screens, a sheet-based
 * drawer on mobile, and a top bar with the user menu.
 *
 * Sidebar anatomy (top to bottom): brand, organization switcher, scrollable
 * grouped navigation, pinned Settings. Only the navigation scrolls, so the
 * workspace context and Settings stay visible at any window height.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <div className="flex min-h-screen">
      <aside className="bg-sidebar sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r md:flex">
        <div className="flex h-14 shrink-0 items-center border-b px-4">
          <Brand />
        </div>
        <SidebarBody />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-background sticky top-0 z-40 flex h-14 items-center gap-2 border-b px-4">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation">
                <MenuIcon />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="bg-sidebar flex w-72 flex-col gap-0 p-0">
              <SheetHeader className="shrink-0 border-b px-4 py-3">
                <SheetTitle asChild>
                  <div>
                    <Brand />
                  </div>
                </SheetTitle>
                <SheetDescription className="sr-only">Application navigation</SheetDescription>
              </SheetHeader>
              <SidebarBody onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>

          <div className="md:hidden">
            <Brand />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <UserMenu />
          </div>
        </header>

        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
