import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

/** The standard action link for MetricCard footers ("View analysis →"). */
export function MetricAction({ href, children = "View analysis" }: { href: string; children?: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="text-primary inline-flex items-center gap-1 text-xs font-medium underline-offset-4 hover:underline"
    >
      {children}
      <ArrowRightIcon className="size-3" aria-hidden="true" />
    </Link>
  );
}
