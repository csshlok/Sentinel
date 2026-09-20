import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

const API_TARGET = process.env.CHANGE_ASSURANCE_API_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
    // Browser development talks to the backend through this same-origin proxy, so the backend's CORS
    // allow-list (which only contains http://localhost:5173) never matters and no origin has to change.
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
});
