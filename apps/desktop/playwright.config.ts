import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  // One retry absorbs keyboard-timing flakes when the whole suite (incl. the 60 s soak) loads the machine.
  retries: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  // Traces and screenshots only on failure, written outside the repo tree's tracked files.
  outputDir: "./test-results",
  use: {
    baseURL: "http://localhost:5173",
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npx vite",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
