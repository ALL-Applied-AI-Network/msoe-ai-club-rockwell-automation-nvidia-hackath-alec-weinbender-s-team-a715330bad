import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, Vite serves the UI on :5173 and forwards API calls to the backend. API_URL overrides where the backend runs.
// `npm run build` writes the UI to dist/, which the backend serves at /.
const api = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api/": api, "/health": api } },
});
