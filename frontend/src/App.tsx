import { useEffect, useState } from "react";

type Health = { status: string; db: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<Health>;
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: "32rem", margin: "4rem auto" }}>
      <h1>Cabinet</h1>
      <p>Numismatics — Coin &amp; Paper Money Collection Manager</p>
      {error ? (
        <p>API unreachable: {error}</p>
      ) : health ? (
        <p>
          API: {health.status} · database: {health.db}
        </p>
      ) : (
        <p>Checking API…</p>
      )}
    </main>
  );
}
