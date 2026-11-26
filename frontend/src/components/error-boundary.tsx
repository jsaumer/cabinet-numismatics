import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Changes when the visitor moves to another page, which clears the error. */
  resetKey: string;
}

/** Catches an error thrown while a page renders. Without one, React takes the
 * whole app down and leaves a blank window; with it, the header and the
 * sidebar stay, and the page says what happened and how to carry on. */
export class PageErrorBoundary extends Component<Props, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="card" role="alert">
        <h1>This page ran into a problem</h1>
        <p>
          Nothing was lost: the collection is as it was. Reload the page, or go somewhere else from
          the sidebar.
        </p>
        <p className="muted">{error.message || String(error)}</p>
        <p className="row">
          <button type="button" className="button primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          <a className="button" href="/">
            Go to the dashboard
          </a>
        </p>
      </div>
    );
  }
}
