"use client";

import * as React from "react";

import { IntelligencePageFrame } from "@/components/intelligence/page-frame";
import { useProjectIntelligence } from "@/components/intelligence/use-project-intelligence";
import { PromptTable } from "@/components/visibility/prompt-table";
import { ResponseDrawer } from "@/components/visibility/response-drawer";
import { useProjectVisibility } from "@/components/visibility/use-project-visibility";
import type { PromptPerformanceRow } from "@/lib/visibility/types";
import { Input } from "@ai-search-growth-os/ui";

/** The stored AI answers, prompt by prompt, with the parsed mentions, claims and citations highlighted. */
export default function AiResponsesPage() {
  const intel = useProjectIntelligence();
  const vis = useProjectVisibility();
  const [open, setOpen] = React.useState<PromptPerformanceRow | null>(null);
  const [query, setQuery] = React.useState("");
  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return vis.prompts.filter((r) => !q || r.prompt.toLowerCase().includes(q));
  }, [vis.prompts, query]);
  return (
    <IntelligencePageFrame intel={intel} title="AI Responses" description="Every prompt with stored AI answers. Open one to read the responses with brand, competitor, citation and claim highlights.">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input aria-label="Search prompts" placeholder="Search prompts…" value={query} onChange={(e) => setQuery(e.target.value)} className="w-64" />
        {!vis.loading && <p className="text-muted-foreground text-xs">{rows.length} prompts with parsed responses in the visibility window</p>}
      </div>
      <PromptTable rows={rows} loading={vis.loading || vis.projectLoading} onOpen={setOpen} />
      <ResponseDrawer prompt={open} brandName={intel.brandName} live={vis.source === "api"} onClose={() => setOpen(null)} />
    </IntelligencePageFrame>
  );
}
