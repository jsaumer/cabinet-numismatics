import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { forgetDemoDismissal } from "./demo-notice";

/** What an empty collection shows, on the dashboard and on the collection
 * page alike: the three ways to get a first piece in. `onLoaded` runs once
 * the demo collection is there, so the page can fetch what it now holds. */
export function Welcome({ onLoaded }: { onLoaded: () => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadDemo() {
    setLoading(true);
    setError(null);
    try {
      await api.loadDemo();
      forgetDemoDismissal();
      onLoaded();
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  return (
    <section className="welcome" aria-labelledby="welcome-title">
      <h2 id="welcome-title">Welcome to Cabinet</h2>
      <p className="welcome-lede">
        Your collection is empty. Cabinet keeps each coin, note, bar, and set with its photos,
        what you paid, and what it's worth. Start any of three ways:
      </p>
      <div className="welcome-actions">
        <div className="welcome-action">
          <h3>Add a piece</h3>
          <p>Type it in, or look it up by name, Numista number, or PCGS cert.</p>
          <Link className="button primary" to="/items/add">
            Add a piece
          </Link>
        </div>
        <div className="welcome-action">
          <h3>Import a collection</h3>
          <p>From your Numista account or export, OpenNumismat, or any spreadsheet.</p>
          <Link className="button" to="/import">
            Import a collection
          </Link>
        </div>
        <div className="welcome-action">
          <h3>Look around first</h3>
          <p>
            Seventeen demo pieces with values. Cabinet fetches their photos from Wikimedia
            Commons, and you can remove the demo in one step.
          </p>
          <button type="button" onClick={loadDemo} disabled={loading}>
            {loading ? "Loading…" : "Load the demo collection"}
          </button>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
