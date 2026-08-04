/// <reference types="vitest/config" />

import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const daemonOrigin = env.SCOPECAT_DAEMON_ORIGIN ?? "http://127.0.0.1:8765";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": {
          target: daemonOrigin,
          changeOrigin: false,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: false,
    },
    test: {
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
