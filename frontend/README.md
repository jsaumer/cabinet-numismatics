# Frontend

React + Vite single-page application (TypeScript). Talks to the backend
through `/api/`. Currently a Phase 0 skeleton that shows API/database health.

- Dev: `npm install`, then `npm run dev` — Vite serves on :5173 and proxies
  `/api` to localhost:8000.
- Build: `npm run build` emits static files to `dist/`.
- In the compose stack, `frontend/Dockerfile` builds the app and produces the
  nginx image used as the `proxy` service — no host Node install needed.
