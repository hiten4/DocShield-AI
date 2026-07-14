import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Polling: inotify events don't cross the Windows->Docker volume mount,
    // so without this, code changes never hot-reload in the container.
    watch: { usePolling: true, interval: 500 },
    proxy: { "/api": { target: "http://backend:8000", changeOrigin: true, rewrite: p => p.replace(/^\/api/, "") } },
  },
});
