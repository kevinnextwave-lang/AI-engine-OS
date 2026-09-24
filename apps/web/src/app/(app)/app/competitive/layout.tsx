"use client";

import * as React from "react";

import { ProjectProvider } from "@/components/project-provider";

/** Competitive pages share the selected project. */
export default function Layout({ children }: { children: React.ReactNode }) {
  return <ProjectProvider>{children}</ProjectProvider>;
}
