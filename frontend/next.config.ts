import type { NextConfig } from "next";

const LAB_BACKEND = process.env.DEV_BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["172.20.165.226"],
  // `standalone` makes `next build` emit a self-contained server in
  // .next/standalone/ that the Docker frontend runtime image copies in.
  // Outside Docker (npm run dev / start) this flag is harmless.
  output: "standalone",
  // Proxy /api/v1/* to the lab backend in dev so the browser never makes
  // a cross-origin request (avoids the CORS allowed-origins restriction).
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${LAB_BACKEND}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
