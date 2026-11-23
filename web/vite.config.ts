/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    // React + router + Radix + motion + React Query land in the main chunk (~230 kB gzip);
    // pages other than Runs are split out with React.lazy.
    chunkSizeWarningLimit: 800,
  },
  server: {
    // The FastAPI service (uv run uvicorn marketsim_api.main:app) listens on :8000.
    proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: true,
  },
});
