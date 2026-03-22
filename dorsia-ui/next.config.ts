import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // Do NOT set NEXT_PUBLIC_* defaults here — they get inlined at build time and would
  // force ws://localhost:8000 even when .env.local only sets NEXT_PUBLIC_API_URL to
  // another host. Use .env.local / deployment env; lib/wsUrl.ts derives WS from API when
  // NEXT_PUBLIC_WS_URL is unset.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-DNS-Prefetch-Control", value: "on" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
