import type { NextConfig } from "next";

// Built as a static site (`npm run build` -> out/) that the Python backend serves at
// http://localhost:8765, so the app keeps working fully offline with a single process.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
