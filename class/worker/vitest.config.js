import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

// The tests call the Worker with their own env, so they need no build output.
export default defineConfig({
  plugins: [cloudflareTest({ main: "./src/index.js", miniflare: { compatibilityDate: "2026-10-01" } })],
});
