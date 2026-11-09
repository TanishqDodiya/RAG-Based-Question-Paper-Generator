import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

// M-02: last-resort guard for unexpected render failures (for example an
// unforeseen malformed field that the defensive preview helpers did not catch).
// It keeps the rest of the application usable and never presents a broken
// paper as valid.
export default class PaperErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
    this.handleReset = this.handleReset.bind(this);
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || 'Unexpected rendering error.',
    };
  }

  componentDidCatch(error, info) {
    // Keep diagnostics in the browser console; do not expose internals in UI.
    console.error('Paper preview render error:', error, info);
  }

  handleReset() {
    this.setState({ hasError: false, message: '' });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="bg-slate-900 border border-rose-500/30 rounded-2xl p-8 text-center shadow-xl space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-rose-500/10 border border-rose-500/30 mx-auto flex items-center justify-center text-rose-300">
            <AlertTriangle className="w-7 h-7" />
          </div>
          <div className="max-w-md mx-auto space-y-1">
            <h3 className="text-base font-semibold text-slate-100">Could not render this paper</h3>
            <p className="text-xs text-slate-400">
              The generated paper contains data the preview could not display. The paper was not
              changed; retry rendering or regenerate the affected question.
            </p>
            <p className="text-[11px] text-slate-500 italic">{this.state.message}</p>
          </div>
          <button
            type="button"
            onClick={this.handleReset}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold border border-slate-700 transition-all inline-flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" /> Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
