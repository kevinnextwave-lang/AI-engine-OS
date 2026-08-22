"use client";

import { Building2Icon, ChevronsUpDownIcon } from "lucide-react";

import { useOrganization } from "@/components/organization-provider";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-search-growth-os/ui";

export function OrganizationSwitcher({ className }: { className?: string }) {
  const { organizations, current, loading, select } = useOrganization();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={className}
          aria-label="Switch organization"
          disabled={loading || organizations.length === 0}
        >
          <Building2Icon className="text-muted-foreground" />
          <span className="max-w-40 truncate">
            {loading ? "Loading…" : (current?.name ?? "No organization")}
          </span>
          <ChevronsUpDownIcon className="text-muted-foreground ml-auto" />
        </Button>
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
