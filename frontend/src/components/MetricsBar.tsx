/**
 * MetricsBar
 *
 * A compact horizontal strip of key-value metrics displayed at the top
 * of the Dashboard. Shows at-a-glance numbers: elapsed time, files written,
 * active agents, overall progress, and WebSocket connection status.
 *
 * Designed to be small enough to sit in a single row without wrapping on most screens.
 */

import { WsConnectionState } from "../lib/websocket";

// ─── Types ────────────────────────────────────────────────────────────────────

interface MetricsBarProps {
  /** ISO timestamp when the job started */
  startedAt: string | null;
  fileCount: number;
  activeAgentCount: number;
  overallProgress: number;
  wsState: WsConnectionState;
  /** Test coverage 0-100, or null if not yet available */
  coverage: number | null;
}

// ─── Elapsed time ─────────────────────────────────────────────────────────────

/**
 * What does this do?
 * Converts a start ISO timestamp to an "Xm Ys" elapsed string.
 * Returns "—" if startedAt is null.
 */
function formatElapsed(startedAt: string | null): string {
  if (!startedAt) return "—";
  const diff = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
  if (diff < 60) return `${diff}s`;
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return `${m}m ${s}s`;
}

// ─── WS state badge ───────────────────────────────────────────────────────────

const WS_BADGE: Record<WsConnectionState, { label: string; color: string }> = {
  connecting: { label: "WS Connecting", color: "text-amber-400" },
  open:       { label: "WS Live",       color: "text-emerald-400" },
  closing:    { label: "WS Closing",    color: "text-slate-500"   },
  closed:     { label: "WS Closed",     color: "text-slate-600"   },
  error:      { label: "WS Error",      color: "text-red-400"     },
};

// ─── Metric chip ─────────────────────────────────────────────────────────────

/**
 * MetricChip
 * One label + value pair in the metrics bar.
 */
function MetricChip({
  label,
  value,
  valueClass = "text-slate-300",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  // What does this do? Renders a single metric with a muted label and prominent value.
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[8px] font-mono uppercase tracking-widest text-slate-600">
        {label}
      </span>
      <span className={`text-sm font-mono font-semibold ${valueClass}`}>{value}</span>
    </div>
  );
}

// ─── Divider ──────────────────────────────────────────────────────────────────

function Divider() {
  return <div className="w-px h-8 bg-slate-800 flex-shrink-0" />;
}

// ─── Main component ───────────────────────────────────────────────────────────

export function MetricsBar({
  startedAt,
  fileCount,
  activeAgentCount,
  overallProgress,
  wsState,
  coverage,
}: MetricsBarProps) {
  const wsBadge = WS_BADGE[wsState];

  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3 rounded-lg border border-slate-800/60 bg-[#070e17]">
      {/* Left cluster */}
      <div className="flex items-center gap-5">
        <MetricChip label="Elapsed" value={formatElapsed(startedAt)} />
        <Divider />
        <MetricChip
          label="Files"
          value={String(fileCount)}
          valueClass="text-cyan-300"
        />
        <Divider />
        <MetricChip
          label="Active"
          value={String(activeAgentCount)}
          valueClass={activeAgentCount > 0 ? "text-cyan-300" : "text-slate-600"}
        />
      </div>

      {/* Centre: progress bar */}
      <div className="flex-1 max-w-xs mx-4">
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 rounded-full transition-all duration-700"
            style={{ width: `${Math.min(100, overallProgress)}%` }}
          />
        </div>
        <p className="text-[9px] font-mono text-center text-slate-600 mt-1">
          {overallProgress}% overall
        </p>
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-5">
        {coverage !== null && (
          <>
            <MetricChip
              label="Coverage"
              value={`${coverage}%`}
              valueClass={
                coverage >= 80
                  ? "text-emerald-400"
                  : coverage >= 60
                  ? "text-amber-400"
                  : "text-red-400"
              }
            />
            <Divider />
          </>
        )}

        {/* WebSocket status */}
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[8px] font-mono uppercase tracking-widest text-slate-600">
            Stream
          </span>
          <span className={`text-[10px] font-mono ${wsBadge.color} flex items-center gap-1`}>
            {wsState === "open" && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
            )}
            {wsBadge.label}
          </span>
        </div>
      </div>
    </div>
  );
}
