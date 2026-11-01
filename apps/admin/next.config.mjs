/** @type {import('next').NextConfig} */

// One public port: this app serves the dashboard, the widget script (/trustdesk.js), the demo page (/demo)
// and proxies the public + admin API (/v1/*) to the internal AI service (never exposed directly).
const AI = (process.env.AI_SERVICE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

export default {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: false, // compression would buffer Server-Sent Events from /v1/public/*/chat/stream
  experimental: { serverActions: { bodySizeLimit: "21mb" } }, // document uploads (API enforces its own limit)
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${AI}/v1/:path*` },
      { source: "/demo", destination: "/demo.html" },
    ];
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Dashboard pages may not be framed; the widget script and API are loaded by other sites.
      { source: "/((?!v1/|trustdesk.js).*)", headers: [{ key: "X-Frame-Options", value: "DENY" }] },
      { source: "/trustdesk.js", headers: [{ key: "Cache-Control", value: "public, max-age=300" }, { key: "Access-Control-Allow-Origin", value: "*" }] },
    ];
  },
};
