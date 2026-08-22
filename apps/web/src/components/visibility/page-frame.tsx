"use client";

import * as React from "react";

import { MockNotice } from "@/components/geo/data-source-badge";
import { PageHeader } from "@/components/shell/page-header";
import { DataBasis } from "@/components/visibility/confidence";
import { VisibilityPageTools } from "@/components/visibility/page-tools";
import { ErrorState, NoDataState, runDisabledReason } from "@/components/visibility/states";
import type { useProjectVisibility } from "@/components/visibility/use-project-visibility";

type Vis = ReturnType<typeof useProjectVisibility>;

/**
 * Shared frame for every AI Visibility page: header with tools, provenance
 * notice, basis line, and the error / empty states. Children render only when
 * there is something measured to show (or while loading, for skeletons).
 */
export function VisibilityPageFrame({
  vis,
  title,
  description,
  children,
}: {
  vis: Vis;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  const loading = vis.loading || vis.projectLoading;
  return (
    <>
      <PageHeader title={title} description={description}>
        <VisibilityPageTools source={vis.source} reason={vis.mockReason} window={vis.window} onWindowChange={vis.setWindow} />
      </PageHeader>
      <MockNotice source={vis.source} reason={vis.mockReason} />
      {vis.error ? (
        <ErrorState message={vis.error} onRetry={vis.actions.refresh} />
      ) : !loading && vis.empty ? (
        <NoDataState
          canRun={runDisabledReason(vis) === null}
          runDisabledReason={runDisabledReason(vis)}
          busy={vis.busy === "run"}
          onRun={() => void vis.actions.runPromptSet()}
          notice={vis.runNotice}
        />
      ) : (
        <>
          {!loading && vis.quality && (
            <div className="mb-4">
              <DataBasis quality={vis.quality} brandName={vis.brandName} />
            </div>
          )}
          {children}
        </>
      )}
    </>
  );
}
