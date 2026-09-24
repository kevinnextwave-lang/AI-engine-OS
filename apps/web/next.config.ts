import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output produces the self-contained server bundle the Docker
  // image runs. Vercel manages its own serverless output and fails with a
  // missing next-server.js.nft.json when standalone is forced, so it is
  // enabled everywhere EXCEPT Vercel builds (Vercel sets VERCEL=1).
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  transpilePackages: ["@ai-search-growth-os/ui", "@ai-search-growth-os/types"],
};

export default nextConfig;
