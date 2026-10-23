import type { NextConfig } from "next";

// FastAPI origin used by the server-side rewrite. The browser never talks to it directly,
// so session cookies stay first-party and CORS is not needed for the web app.
// Rewrites are resolved at build time: set API_INTERNAL_URL before `next build`.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

// Pages only (not /api/*, whose PDFs open in the browser's viewer). Scripts are not restricted
// here: Next.js hydration needs inline scripts, and a nonce-based script policy would force every
// page to render dynamically. What is locked down: framing, plugins, <base> and form targets.
const pageContentSecurityPolicy = [
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      {
        source: "/((?!api/).*)",
        headers: [{ key: "Content-Security-Policy", value: pageContentSecurityPolicy }],
      },
    ];
  },
};

export default nextConfig;
