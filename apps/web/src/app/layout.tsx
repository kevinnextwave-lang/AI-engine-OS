import type { Metadata } from "next";
import localFont from "next/font/local";
import { AuthProvider } from "@/components/auth-provider";
import { TooltipProvider } from "@ai-search-growth-os/ui";

import "./globals.css";

// The design system's UI face (see packages/ui/DESIGN.md). Self-hosted
// (fonts/inter-latin-variable.woff2, SIL OFL) so builds never depend on
// Google Fonts being reachable. Exposed as a CSS variable that
// packages/ui/styles.css folds into --font-sans.
const inter = localFont({
  src: "./fonts/inter-latin-variable.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Search Growth OS",
  description: "Understand and improve how your brand appears across AI search engines.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans antialiased">
        <TooltipProvider>
          <AuthProvider>{children}</AuthProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
