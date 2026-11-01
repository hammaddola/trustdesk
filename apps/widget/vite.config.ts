import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Production build: one self-contained IIFE (JS + inlined CSS), no code splitting, no external assets.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // Library mode does not replace process.env.NODE_ENV; React needs it at build time.
  define: { "process.env.NODE_ENV": JSON.stringify(mode === "production" ? "production" : "development") },
  build: {
    target: "es2019",
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    sourcemap: false,
    lib: {
      entry: "src/loader.tsx",
      name: "TrustDesk",
      formats: ["iife"],
      fileName: () => "trustdesk.js",
    },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
  test: {
    environment: "jsdom",
    css: { include: /.+/ }, // process Tailwind so the ?inline stylesheet is real in tests
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
