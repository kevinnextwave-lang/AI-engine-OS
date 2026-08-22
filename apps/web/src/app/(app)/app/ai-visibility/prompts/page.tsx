"use client";

import * as React from "react";

import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { PromptTable } from "@/components/visibility/prompt-table";
import { ResponseDrawer } from "@/components/visibility/response-drawer";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import { CATEGORY_LABEL } from "@/lib/visibility/labels";
import type { PromptPerformanceRow } from "@/lib/visibility/types";
import type { PromptCategory } from "@ai-search-growth-os/types";
import { Input, NativeSelect } from "@ai-search-growth-os/ui";

export default function PromptsPage() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const [open, setOpen] = React.useState<PromptPerformanceRow | null>(null);
  const [query, setQuery] = React.useState("");
  const [category, setCategory] = React.useState<PromptCategory | "">("");

  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return vis.prompts.filter((r) => (!category || r.category === category) && (!q || r.prompt.toLowerCase().includes(q)));
  }, [vis.prompts, query, category]);

  return (
    <VisibilityPageFrame
      vis={vis}
      title="Prompts"
      description="Per-prompt results: how often each question led to a brand mention, a recommendation, and where the brand was listed. Open a prompt to read the answers."
    >
      <div className="mb-3 flex flex-wrap gap-2">
        <Input aria-label="Search prompts" placeholder="Search prompts…" value={query} onChange={(e) => setQuery(e.target.value)} className="w-64" />
        <NativeSelect aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value as PromptCategory | "")} className="w-48">
          <option value="">All categories</option>
          {(Object.keys(CATEGORY_LABEL) as PromptCategory[]).map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABEL[c]}
            </option>
          ))}
        </NativeSelect>
        {!loading && (
          <p className="text-muted-foreground self-center text-xs">
            {rows.length} of {vis.prompts.length} prompts
          </p>
        )}
      </div>
      <PromptTable rows={rows} loading={loading} onOpen={setOpen} />
      <ResponseDrawer prompt={open} brandName={vis.brandName} live={vis.source === "api"} onClose={() => setOpen(null)} />
    </VisibilityPageFrame>
  );
}
