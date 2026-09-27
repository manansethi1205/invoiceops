import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: "html",
  snapshotPathTemplate: "{testDir}/{testFilePath}-snapshots/{arg}{ext}",
  use: { baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure" },
  webServer: {
    command: "node scripts/start-standalone.mjs",
    url: "http://127.0.0.1:3000/dashboard",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { ...process.env, HOSTNAME: "127.0.0.1", PORT: "3000" },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
