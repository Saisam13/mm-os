import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Item Code Studio's own frontend, built and served from the same container/port as the
// API — mirrors servicedesk/frontend/vite.config.js.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8020",
      "/_mmos": "http://localhost:8020",
      "/_dev": "http://localhost:8020",
    },
  },
});
