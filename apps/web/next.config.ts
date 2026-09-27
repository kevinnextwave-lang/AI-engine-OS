import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output produces the self-contained server bundle the Docker
  // image runs. Vercel manages its own serverless output and fails with a
  // missing next-server.js.nft.json when standalone is forced, so it is
  // enabled everywhere EXCEPT Vercel builds (Vercel sets VERCEL=1).
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  transpilePackages: ["@ai-search-growth-os/ui", "@ai-search-growth-os/types"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          // The app never needs to be embedded; frame-ancestors is the
          // modern control, X-Frame-Options covers older browsers.
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // A full script-src CSP is deliberately NOT set yet: the theme
          // bootstrap is an inline script and would need nonce plumbing
          // through the root layout first. Tracked as follow-up work.
        ],
      },
    ];
  },
};

export default nextConfig;
