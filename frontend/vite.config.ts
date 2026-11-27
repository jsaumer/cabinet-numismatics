import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The release this build belongs to, from the one place a version is written
// (the backend's pyproject.toml, which /api/health reports). Baked in as
// __CABINET_VERSION__ so the page can tell when the proxy image it came from
// and the backend it talks to are different releases. frontend/Dockerfile
// copies the file to the same relative place; a build that can't find it
// fails rather than ship a page that can't tell.
function cabinetVersion(): string {
  const text = readFileSync(new URL("../backend/pyproject.toml", import.meta.url), "utf8");
  const match = /^version\s*=\s*"([^"]+)"/m.exec(text);
  if (!match) throw new Error("no version in backend/pyproject.toml");
  return match[1];
}

export default defineConfig({
  plugins: [react()],
  define: {
    __CABINET_VERSION__: JSON.stringify(cabinetVersion()),
  },
  server: {
    // Dev server only; in production nginx does this proxying.
    proxy: {
      "/api": "http://localhost:8000",
      // Photos are served by nginx; point at the compose stack when it's up.
      "/photos": "http://localhost",
    },
  },
});
