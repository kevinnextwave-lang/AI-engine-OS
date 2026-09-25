import type * as React from "react";

/**
 * Props that make a click-to-open table row keyboard-accessible: focusable,
 * announced as a button, activated with Enter or Space. Use for rows whose
 * whole surface opens a drawer/detail; the row's text content is the
 * accessible name, so pass `label` only when that text isn't descriptive.
 *
 * (Prefer a real button/link inside the row when the design has one — this
 * helper is for the established whole-row-click pattern.)
 */
export function rowButtonProps<T extends HTMLElement>(
  onActivate: () => void,
  label?: string,
): Pick<React.HTMLAttributes<T>, "role" | "tabIndex" | "onClick" | "onKeyDown" | "aria-label"> {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    onClick: onActivate,
    onKeyDown: (e: React.KeyboardEvent<T>) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate();
      }
    },
  };
}
