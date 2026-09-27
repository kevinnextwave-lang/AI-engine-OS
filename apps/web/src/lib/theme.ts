"use client";

import * as React from "react";

/**
 * Theme preference: "system" follows the OS, "light"/"dark" pin it.
 * The design system's dark tokens have existed since the token pass —
 * this store is what finally applies them (`.dark` on <html>). A no-flash
 * bootstrap script in the root layout applies the stored choice before
 * first paint; this store keeps it in sync afterwards (including live OS
 * changes while on "system").
 */

export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "asg:theme";
const listeners = new Set<() => void>();

export function readTheme(): ThemePreference {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(pref: ThemePreference): void {
  const dark = pref === "dark" || (pref === "system" && systemDark());
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function setTheme(pref: ThemePreference): void {
  try {
    if (pref === "system") window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* preference still applies for this page */
  }
  applyTheme(pref);
  listeners.forEach((cb) => cb());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onSystemChange = () => {
    if (readTheme() === "system") applyTheme("system");
    cb();
  };
  mq.addEventListener("change", onSystemChange);
  return () => {
    listeners.delete(cb);
    mq.removeEventListener("change", onSystemChange);
  };
}

/** Current preference, hydration-safe (server renders as "system"). */
export function useTheme(): { theme: ThemePreference; setTheme: (p: ThemePreference) => void } {
  const theme = React.useSyncExternalStore(subscribe, readTheme, () => "system" as const);
  return { theme, setTheme };
}

/** Inline no-flash bootstrap for the root layout <head>. Kept tiny and
 * dependency-free; mirrors readTheme/applyTheme exactly. */
export const THEME_BOOTSTRAP = `(function(){try{var v=localStorage.getItem("${STORAGE_KEY}");var d=v==="dark"||(v!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);document.documentElement.style.colorScheme=d?"dark":"light";}catch(e){}})();`;
