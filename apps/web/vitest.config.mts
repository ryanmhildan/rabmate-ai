import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Format tests assert Asia/Jakarta output regardless of the machine's zone.
    env: { TZ: "UTC" },
    // Form tests type character by character (user-event); with every file running in parallel on
    // a Windows dev machine some take over the 5 s default. Assertions are unchanged.
    testTimeout: 15_000,
  },
});
