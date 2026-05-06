import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["172.20.165.226"],
  // `standalone` makes `next build` emit a self-contained server in
  // .next/standalone/ that the Docker frontend runtime image copies in.
  // Outside Docker (npm run dev / start) this flag is harmless.
  output: "standalone",
};

export default nextConfig;
