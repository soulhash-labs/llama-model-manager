import { build } from "esbuild";
import { execSync } from "node:child_process";

const mode = process.argv[2] || "all";
const MCP_EXTERNALS = ["domino", "turndown"];

async function buildMcp() {
  await build({
    entryPoints: ["src/index.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "ES2022",
    outdir: "dist",
    sourcemap: false,
    minify: false,
    external: MCP_EXTERNALS,
  });
}

async function buildHooks() {
  await build({
    entryPoints: ["src/hooks/runner.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "ES2022",
    outdir: "dist/hooks",
    sourcemap: false,
    minify: false,
  });
}

function buildDashboard() {
  execSync("npx vite build --config dashboard/vite.config.ts", {
    stdio: "inherit",
    cwd: process.cwd(),
  });
}

(async () => {
  if (mode === "mcp" || mode === "all") {
    await buildMcp();
    await buildHooks();
  }
  if (mode === "dashboard" || mode === "all") {
    buildDashboard();
  }
})();
