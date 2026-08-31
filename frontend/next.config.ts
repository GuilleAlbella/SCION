import type { NextConfig } from "next";

const DEV_BACKEND = process.env.DEV_BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["172.20.165.226"],
  // `standalone` makes `next build` emit a self-contained server in
  // .next/standalone/ that the Docker frontend runtime image copies in.
  // Outside Docker (npm run dev / start) this flag is harmless.
  output: "standalone",
  async rewrites() {
    // In dev (npm run dev), proxy /api/v1/* to the FastAPI backend so the
    // browser never touches port 8000 directly and CORS is a non-issue.
    // In production the nginx reverse-proxy handles this; the rewrite is
    // a no-op because NEXT_PUBLIC_API_BASE_URL is set to /api/v1 there too.
    return [
      {
        source: "/api/v1/:path*",
        destination: `${DEV_BACKEND}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
