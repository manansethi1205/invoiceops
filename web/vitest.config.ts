import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"], exclude: ["e2e/**", "oidc/**", "node_modules/**", ".next/**"] },
  resolve: { alias: {
    "@": fileURLToPath(new URL("./src", import.meta.url)),
    "server-only": fileURLToPath(new URL("./src/test/server-only.ts", import.meta.url)),
  } },
});
