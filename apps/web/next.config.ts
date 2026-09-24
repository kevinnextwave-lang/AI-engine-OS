import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle so the Docker image only ships what it runs.
  output: "standalone",
  transpilePackages: ["@ai-search-growth-os/ui", "@ai-search-growth-os/types"],
};

export default nextConfig;
