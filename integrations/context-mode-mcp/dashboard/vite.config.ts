import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  root: resolve(process.cwd(), "dashboard"),
  plugins: [react()],
  build: {
    outDir: resolve(process.cwd(), "dashboard", "dist"),
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@": resolve(process.cwd(), "dashboard/src"),
    },
  },
  server: {
    host: true,
    port: 4747,
  },
});
