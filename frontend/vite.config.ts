/**
 * vite.config.ts
 * Vite configuration for the Swarm Factory frontend.
 *
 * Key points:
 *  - Uses @vitejs/plugin-react for HMR + JSX transform
 *  - Proxies /api/* and /ws/* to the backend during `vite dev`
 *    so you don't need CORS headers locally
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// What does this do? Exports the Vite config with React plugin + dev proxy.
export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,
    proxy: {
      // What does this do? Forwards all /api/* requests to the FastAPI backend.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // What does this do? Upgrades /ws/* requests to WebSocket connections.
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: "dist",
    sourcemap: true,
    // What does this do? Splits vendor libraries into a separate chunk for better caching.
    rollupOptions: {
      output: {
        manualChunks: {
          react:  ["react", "react-dom"],
          router: ["react-router-dom"],
        },
      },
    },
  },
});
