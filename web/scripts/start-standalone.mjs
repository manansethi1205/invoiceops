import { cpSync, existsSync } from "node:fs";

const standaloneRoot = new URL("../.next/standalone/", import.meta.url);
const staticSource = new URL("../.next/static/", import.meta.url);
const staticTarget = new URL("../.next/standalone/.next/static/", import.meta.url);
const publicSource = new URL("../public/", import.meta.url);
const publicTarget = new URL("../.next/standalone/public/", import.meta.url);

if (!existsSync(standaloneRoot)) {
  throw new Error("Standalone build is missing. Run `pnpm build` before browser tests.");
}
cpSync(staticSource, staticTarget, { recursive: true });
if (existsSync(publicSource)) cpSync(publicSource, publicTarget, { recursive: true });

await import("../.next/standalone/server.js");
