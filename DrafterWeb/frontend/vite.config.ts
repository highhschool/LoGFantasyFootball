import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // Built assets land where FastAPI already serves static files, so production
  // is a single origin with no CORS and no second server to run.
  build: {
    outDir: "../backend/app/static",
    emptyOutDir: true,
  },

  server: {
    port: 5173,
    // In dev the app runs on 5173 and the API on 8000; proxying keeps the
    // frontend calling same-origin /api paths in both environments.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
