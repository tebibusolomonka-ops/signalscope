import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The development server passes /api to the SignalScope API, so the browser
// talks to one origin and the API needs no CORS setup.
const apiTarget = process.env.SIGNALSCOPE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: apiTarget,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    testTimeout: 20000,
  },
});
