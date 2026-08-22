"use client";

import * as React from "react";

import { ProjectProvider } from "@/components/project-provider";

export default function AiIntelligenceLayout({ children }: { children: React.ReactNode }) {
  return <ProjectProvider>{children}</ProjectProvider>;
}
