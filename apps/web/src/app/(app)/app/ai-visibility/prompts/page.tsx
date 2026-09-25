"use client";

import { useSearchParams } from "next/navigation";
import * as React from "react";

import { VisibilityPageFrame } from "@/components/visibility/page-frame";
import { PromptTable } from "@/components/visibility/prompt-table";
import { ResponseDrawer } from "@/components/visibility/response-drawer";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import { CATEGORY_LABEL } from "@/lib/visibility/labels";
import type { PromptPerformanceRow } from "@/lib/visibility/types";
import type { PromptCategory } from "@ai-search-growth-os/types";
import { Input, NativeSelect, SegmentedControl } from "@ai-search-growth-os/ui";

type MentionFilter = "all" | "mentioned" | "missing";

function PromptsPageInner() {
  const vis = useProjectVisibility();
  const loading = vis.loading || vis.projectLoading;
  const params = useSearchParams();
  const [open, setOpen] = React.useState<PromptPerformanceRow | null>(null);
  const [query, setQuery] = React.useState("");
  const [category, setCategory] = React.useState<PromptCategory | "">("");
  // The overview's funnel links here pre-filtered (?filter=mentioned|missing).
  const initial = params.get("filter");
  const [mention, setMention] = React.useState<MentionFilter>(
    initial === "mentioned" || initial === "missing" ? initial : "all",
  );

  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return vis.prompts.filter(
      (r) =>
        (!category || r.category === category) &&
        (!q || r.prompt.toLowerCase().includes(q)) &&
        (mention === "all" || (mention === "mentioned" ? r.mentions > 0 : r.mentions === 0)),
    );
  }, [vis.prompts, query, category, mention]);
  const missing = vis.prompts.filter((r) => r.sampleSize > 0 && r.mentions === 0).length;

  return (
    <VisibilityPageFrame
      vis={vis}
      hasOwnContent={vis.prompts.length > 0}
      title="Prompts"
      description="Per-prompt results: how often each question led to a brand mention, a recommendation, and where the brand was listed. Open a prompt to read the answers."
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SegmentedControl
          aria-label="Mention filter"
          value={mention}
          onValueChange={(v) => setMention(v as MentionFilter)}
          options={[
            { value: "all", label: "All" },
            { value: "mentioned", label: "Mentioned" },
            { value: "missing", label: `Not mentioned${missing > 0 ? ` (${missing})` : ""}` },
          ]}
        />
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
      <PromptTable
        rows={rows}
        loading={loading}
        onOpen={setOpen}
        emptyTitle={mention === "missing" ? "No prompts without a mention" : undefined}
        emptyDescription={
          mention === "missing"
            ? "Every prompt with responses in this window mentioned your brand at least once."
            : undefined
        }
      />
      <ResponseDrawer prompt={open} brandName={vis.brandName} live={vis.source === "api"} onClose={() => setOpen(null)} />
    </VisibilityPageFrame>
  );
}

export default function PromptsPage() {
  // useSearchParams requires a Suspense boundary in the app router.
  return (
    <React.Suspense fallback={null}>
      <PromptsPageInner />
    </React.Suspense>
  );
}
