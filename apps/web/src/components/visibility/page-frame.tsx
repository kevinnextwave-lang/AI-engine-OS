"use client";

import * as React from "react";

import { AppPageFrame } from "@/components/shell/app-page-frame";
import { DataBasis } from "@/components/visibility/confidence";
import { VisibilityPageTools } from "@/components/visibility/page-tools";
import { NoDataState, runDisabledReason } from "@/components/visibility/states";
import type { useProjectVisibility } from "@/components/visibility/use-project-visibility";

type Vis = ReturnType<typeof useProjectVisibility>;

/**
 * Frame for the AI Visibility pages: shared chrome via AppPageFrame, plus
 * this domain's specifics — the data-basis line and the no-responses empty
 * state with its run/generate actions.
 */
export function VisibilityPageFrame({
  vis,
  title,
  description,
  hasOwnContent = false,
  children,
}: {
  vis: Vis;
  title: string;
  description: string;
  /** Skip the no-responses empty state: the page has content of its own
   * (e.g. the prompt list, which must be reviewable before any run). */
  hasOwnContent?: boolean;
  children: React.ReactNode;
}) {
  const loading = vis.loading || vis.projectLoading;
  const showEmpty = !loading && vis.empty && !hasOwnContent;
  return (
    <AppPageFrame
      title={title}
      description={description}
      tools={<VisibilityPageTools source={vis.source} reason={vis.mockReason} window={vis.window} onWindowChange={vis.setWindow} />}
      source={vis.source}
      mockReason={vis.mockReason}
      error={vis.error}
      errorWhat="AI visibility data"
      onRetry={vis.actions.refresh}
      gate={
        showEmpty ? (
          <NoDataState
            canRun={runDisabledReason(vis) === null}
            runDisabledReason={runDisabledReason(vis)}
            busy={vis.busy === "run"}
            generating={vis.busy === "generate"}
            needsPrompts={vis.source === "api" && vis.runnableSet === null}
            onRun={() => void vis.actions.runPromptSet()}
            onGenerate={() => void vis.actions.generatePrompts()}
            notice={vis.runNotice}
          />
        ) : null
      }
    >
      {!loading && vis.quality && (
        <div className="mb-4">
          <DataBasis quality={vis.quality} brandName={vis.brandName} />
        </div>
      )}
      {children}
    </AppPageFrame>
  );
}
