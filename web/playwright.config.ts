import { defineConfig, devices } from "@playwright/test";

const PORT = 5174;

/** End-to-end + accessibility checks against the dev server with the mock API. */
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  // pages load several lazy chunks and mock requests; under parallel load 5 s is too tight
  expect: { timeout: 10_000 },
  fullyParallel: true,
  // one Vite dev server compiles pages on first request; too many workers starve it
  workers: process.env.CI ? undefined : 6,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: `node node_modules/vite/bin/vite.js --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    env: { VITE_API_MOCK: "true" },
    timeout: 60_000,
  },
});
