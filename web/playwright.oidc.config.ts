import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./oidc",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:3000",
    ...devices["Desktop Chrome"],
    // Real OIDC responses contain tokens; never retain traces or screenshots.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
