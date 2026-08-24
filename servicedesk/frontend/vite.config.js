import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Service Desk's own frontend, built and served from the same container/port as the API —
// docs/09-build-agents.md's pattern, mirrored from backend/app/main.py's frontend/dist mount.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8010",
      "/_mmos": "http://localhost:8010",
    },
  },
});
