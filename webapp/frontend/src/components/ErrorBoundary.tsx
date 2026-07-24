import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/** Renders a recoverable inline error instead of a blank white screen. A component
 * throwing (a malformed parser record, a bad route param) never takes down in-flight
 * upload progress either way, since that state lives in the module-level uploadManager,
 * not in any component under this boundary — remounting the tree just resubscribes to
 * the same running manager instead of losing progress. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("sysdx: caught render error", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="card" style={{ margin: 24 }}>
          <h3>Something went wrong rendering this view</h3>
          <p className="muted mono">{this.state.error.message}</p>
          <button className="secondary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
