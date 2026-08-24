import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    // Internal, VPN-only app on evergreen browsers (see docs/06-network-security.md);
    // esnext lets src/api/index.ts use a top-level await for the dev-mock switch
    // without esbuild needing to downlevel it.
    target: 'esnext',
  },
})
