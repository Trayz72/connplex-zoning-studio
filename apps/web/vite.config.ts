import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // More specific rule first — Vite checks proxy prefixes in key order, and
      // /api/pm must win over the broader /api rule below so it reaches the
      // project/auth service rather than the zoning engine.
      '/api/pm': { target: 'http://localhost:3001', changeOrigin: true },
      '/api': { target: 'http://localhost:8000', changeOrigin: true }
    }
  }
});
