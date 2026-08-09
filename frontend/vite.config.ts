import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev server only; in production nginx does this proxying.
    proxy: {
      "/api": "http://localhost:8000",
      // Photos are served by nginx; point at the compose stack when it's up.
      "/photos": "http://localhost",
    },
  },
});
