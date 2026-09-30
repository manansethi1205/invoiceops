import { defineConfig, devices } from "@playwright/test";

const testPort = process.env.PLAYWRIGHT_TEST_PORT ?? "3107";
const baseURL = `http://127.0.0.1:${testPort}`;

export default defineConfig({
  testDir: "./e2e",
  // Full-page screenshots can race over the shared Windows scrollbar when browser
  // contexts render concurrently. This small visual suite favors deterministic baselines.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: "html",
  snapshotPathTemplate: "{testDir}/{testFilePath}-snapshots/{arg}{ext}",
  use: { baseURL, trace: "retain-on-failure" },
  webServer: {
    command: "node scripts/start-standalone.mjs",
    url: `${baseURL}/dashboard`,
    reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === "1" && !process.env.CI,
    timeout: 120_000,
    env: { ...process.env, HOSTNAME: "127.0.0.1", PORT: testPort },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
