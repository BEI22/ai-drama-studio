import type { NextConfig } from "next";

// `output: "standalone"` is only needed for the production Docker image; using it
// locally makes `next start` refuse to run (it expects `node server.js`), so it is
// opt-in via NEXT_OUTPUT_STANDALONE=1 (set in the Dockerfile builder stage).
const standalone = process.env.NEXT_OUTPUT_STANDALONE === "1";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(standalone ? { output: "standalone" as const } : {}),
  env: {
    NEXT_PUBLIC_REQUEST_ID_HEADER:
      process.env.NEXT_PUBLIC_REQUEST_ID_HEADER ?? "X-Request-ID",
  },
};

export default nextConfig;
