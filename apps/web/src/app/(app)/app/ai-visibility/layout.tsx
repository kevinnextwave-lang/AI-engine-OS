"use client";

import * as React from "react";

import { ProjectProvider } from "@/components/project-provider";

/** AI Visibility pages share the selected project. */
export default function AiVisibilityLayout({ children }: { children: React.ReactNode }) {
  return <ProjectProvider>{children}</ProjectProvider>;
}
