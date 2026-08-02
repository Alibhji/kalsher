import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * Without this, a single throw anywhere in the tree unmounts the whole app and
 * leaves the bare dark page body, with the cause visible only in the console.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI crashed:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-xl rounded-lg border border-rose-500/40 bg-rose-500/10 p-6">
          <h1 className="text-lg font-semibold text-rose-200">Dashboard crashed</h1>
          <p className="mt-2 text-sm text-slate-300">
            The interface hit an unexpected error. Live data kept streaming in the background, so
            reloading usually restores it.
          </p>
          <pre className="mt-4 max-h-48 overflow-auto rounded bg-slate-950/60 p-3 text-xs text-rose-300">
            {error.message}
          </pre>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded bg-slate-700 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-600"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded bg-teal-600 px-3 py-1.5 text-sm text-white hover:bg-teal-500"
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}
