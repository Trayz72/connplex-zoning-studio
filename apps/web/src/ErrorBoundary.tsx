import React from 'react';
import { WarningIcon } from './components/Icons';

interface State {
  error: Error | null;
}

/** Without this, any unhandled render error anywhere in the tree white-
 * screens the whole app with no recovery path — confirmed there was no
 * error boundary anywhere before this. A CAD-editing tool with a lot of
 * geometry-shaped data flowing into render will hit edge cases; this at
 * least gives the architect a way back instead of a blank tab. */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Unhandled UI error:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          minHeight: '100vh', padding: '2rem', textAlign: 'center', gap: '1rem'
        }}>
          <WarningIcon size={28} className="text-tertiary" />
          <h1 style={{ fontSize: 'var(--text-xl)', fontWeight: 600 }}>Something went wrong</h1>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', fontSize: 'var(--text-base)' }}>
            This page hit an unexpected error and can't continue. Your project data on the
            server is unaffected — reloading usually resolves it.
          </p>
          <pre style={{
            maxWidth: '600px', overflow: 'auto', fontSize: 'var(--text-sm)', color: 'var(--danger)',
            background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
            borderRadius: '6px', padding: '0.75rem', textAlign: 'left'
          }}>
            {this.state.error.message}
          </pre>
          <button className="btn btn-primary" onClick={() => window.location.href = '/projects'}>
            Back to Projects
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
