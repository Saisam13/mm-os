import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Password Manager's own frontend, built and served the same way servicedesk's is —
// docs/09-build-agents.md's pattern. This shell has nothing to proxy except the
// placeholder auth calls below.
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
