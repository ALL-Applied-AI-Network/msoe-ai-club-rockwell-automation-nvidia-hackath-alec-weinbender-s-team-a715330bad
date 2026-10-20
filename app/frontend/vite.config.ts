import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, Vite serves the UI on :5173 and forwards API calls to the backend. API_URL overrides where the backend runs.
const api = process.env.API_URL ?? "http://localhost:8000";
const page = (name: string) => fileURLToPath(new URL(name, import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api/": api, "/health": api } },
  // Two pages until the new UI replaces the old one: index.html is the old single-file UI, app.html the new React app.
  // Only app.html is built. The backend serves index.html straight from this folder, and Vite's build can't bundle it
  // (it loads three.js from a CDN through an import map).
  build: { rolldownOptions: { input: { app: page("app.html") } } },
});
