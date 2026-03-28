import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",   // enables Docker-optimized build
  async rewrites() {
    // Proxy /api/* → FastAPI backend in dev; in prod use Nginx
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
