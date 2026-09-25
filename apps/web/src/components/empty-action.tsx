import Link from "next/link";
import * as React from "react";

import { Button } from "@ai-search-growth-os/ui";

/** The standard primary CTA for empty states that navigate somewhere. */
export function EmptyAction({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Button asChild size="sm">
      <Link href={href}>{children}</Link>
    </Button>
  );
}
