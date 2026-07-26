import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const daemonOrigin = env.SCOPECAT_DAEMON_ORIGIN ?? "http://127.0.0.1:8765";

  return {
    plugins: [react()],
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
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/**/*.d.ts"],
        reporter: ["text-summary"],
      },
    },
  };
});
