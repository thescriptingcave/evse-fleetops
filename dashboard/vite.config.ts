import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Backend URL for the dev proxy; matches `API_PORT` in the Makefile.
const apiUrl = process.env.EVSE_API_URL ?? "http://localhost:8010";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiUrl,
        changeOrigin: true,
      },
    },
  },
});