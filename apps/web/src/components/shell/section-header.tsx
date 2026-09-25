import Link from "next/link";
import * as React from "react";

/**
 * The one in-page section heading. Hierarchy below the page title:
 * section title (text-lg semibold) + optional one-line hint + optional
 * action on the right. Always followed by the section body with the
 * standard mb-3 gap this component carries.
 */
export function SectionHeader({
  title,
  hint,
  href,
  linkLabel = "Open",
  children,
}: {
  title: string;
  hint?: string;
  /** Optional "open the full view" link on the right. */
  href?: string;
  linkLabel?: string;
  /** Custom right-side content; overrides href. */
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {hint && <p className="text-muted-foreground mt-0.5 text-sm leading-relaxed">{hint}</p>}
      </div>
      {children ??
        (href && (
          <Link href={href} className="text-primary shrink-0 text-sm underline-offset-4 hover:underline">
            {linkLabel}
          </Link>
        ))}
    </div>
  );
}
