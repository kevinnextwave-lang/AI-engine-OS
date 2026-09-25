"use client";

import { Building2Icon, ChevronsUpDownIcon } from "lucide-react";

import { useOrganization } from "@/components/organization-provider";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-search-growth-os/ui";

/**
 * Organization (account) switcher.
 *
 * `variant="sidebar"` renders the two-line workspace row used at the top of
 * the sidebar: org name + the caller's role, with a quiet bordered surface so
 * it reads as "where am I" rather than as a button.
 */
export function OrganizationSwitcher({
  className,
  variant = "default",
}: {
  className?: string;
  variant?: "default" | "sidebar";
}) {
  const { organizations, current, loading, select } = useOrganization();
  const disabled = loading || organizations.length === 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {variant === "sidebar" ? (
          <button
            type="button"
            aria-label="Switch organization"
            disabled={disabled}
            className={cn(
              "bg-background/60 flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors",
              "hover:bg-sidebar-accent/50 disabled:opacity-70",
              className,
            )}
          >
            <span className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
              <Building2Icon className="size-4" aria-hidden="true" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[13px] leading-tight font-medium">
                {loading ? "Loading…" : (current?.name ?? "No organization")}
              </span>
              {current?.role && (
                <span className="text-muted-foreground truncate text-[11px] leading-tight capitalize">
                  {current.role}
                </span>
              )}
            </span>
            <ChevronsUpDownIcon className="text-muted-foreground size-3.5 shrink-0" aria-hidden="true" />
          </button>
        ) : (
          <Button variant="outline" className={className} aria-label="Switch organization" disabled={disabled}>
            <Building2Icon className="text-muted-foreground" />
            <span className="max-w-40 truncate">
              {loading ? "Loading…" : (current?.name ?? "No organization")}
            </span>
            <ChevronsUpDownIcon className="text-muted-foreground ml-auto" />
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Organizations</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup value={current?.id ?? ""} onValueChange={select}>
          {organizations.map((org) => (
            <DropdownMenuRadioItem key={org.id} value={org.id}>
              <span className="flex flex-1 flex-col">
                <span className="truncate">{org.name}</span>
                <span className="text-muted-foreground text-xs capitalize">{org.role}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
