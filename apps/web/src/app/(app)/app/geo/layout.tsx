"use client";

import * as React from "react";

import { ProjectProvider } from "@/components/project-provider";

/** GEO pages share the selected project. */
export default function GeoLayout({ children }: { children: React.ReactNode }) {
  return <ProjectProvider>{children}</ProjectProvider>;
}
