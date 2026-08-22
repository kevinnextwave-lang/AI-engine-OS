"use client";

import { FolderKanbanIcon } from "lucide-react";

import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@ai-search-growth-os/ui";

export default function ProjectsPage() {
  const { current } = useOrganization();

  return (
    <>
      <PageHeader
        title="Projects"
        description={
          current ? `Brands and websites tracked by ${current.name}.` : "Brands and websites you track."
        }
      >
        <Button disabled title="Available in the next milestone">
          New project
        </Button>
      </PageHeader>
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
        <FolderKanbanIcon className="text-muted-foreground mb-3 size-8" aria-hidden="true" />
        <p className="font-medium">No projects yet</p>
        <p className="text-muted-foreground mt-1 max-w-sm text-sm">
          Projects group a brand&apos;s domains, competitors and tracked prompts. Creating them is
          part of the next milestone.
        </p>
      </div>
    </>
  );
}
