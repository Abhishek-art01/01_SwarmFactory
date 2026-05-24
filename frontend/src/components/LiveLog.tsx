/**
 * LiveLog
 *
 * A terminal-style scrolling log feed that displays real-time messages
 * from the swarm agents. New lines are appended at the bottom and the
 * panel auto-scrolls to keep the latest entry visible.
 *
 * Log levels are colour-coded:
 *  info  → cyan / default
 *  warn  → amber
 *  error → red
 *
 * Accepts the `logs` array from useSwarm.
 */

import { useEffect, useRef } from "react";
import { LogLine } from "../hooks/useSwarm";

// ─── Types ────────────────────────────────────────────────────────────────────

interface LiveLogProps {
  logs: LogLine[];
  /** Max height of the scroll container (Tailwind class, default max-h-64) */
  maxHeightClass?: string;
  /** Whether to auto-scroll to bottom on new entries (default true) */
  autoScroll?: boolean;
}

// ─── Level styles ─────────────────────────────────────────────────────────────

const LEVEL_COLOR: Record<LogLine["level"], string> = {
  info: "text-cyan-500/60",
  warn: "text-amber-400",
  error: "text-red-400",
};

const LEVEL_PREFIX: Record<LogLine["level"], string> = {
  info: "INFO",
  warn: "WARN",
  error: "ERR ",
};

// ─── Sub-component: log row ───────────────────────────────────────────────────

/**
 * LogRow
 * One line of the log output.
 */
function LogRow({ line }: { line: LogLine }) {
  // What does this do? Renders a single log entry with timestamp, level badge, agent, and message.
  const time = new Date(line.timestamp).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex items-start gap-2 text-[11px] font-mono leading-relaxed hover:bg-white/[0.02] px-1 rounded">
      {/* Timestamp */}
      <span className="text-slate-700 flex-shrink-0 select-none">{time}</span>

      {/* Level badge */}
      <span className={`flex-shrink-0 ${LEVEL_COLOR[line.level]}`}>
        [{LEVEL_PREFIX[line.level]}]
      </span>

      {/* Agent name */}
      {line.agent && (
        <span className="text-slate-500 flex-shrink-0 max-w-[80px] truncate">
          {line.agent}
        </span>
      )}

      {/* Message */}
      <span
        className={`flex-1 break-words ${
          line.level === "error"
            ? "text-red-300"
            : line.level === "warn"
            ? "text-amber-300/80"
            : "text-slate-400"
        }`}
      >
        {line.message}
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function LiveLog({
  logs,
  maxHeightClass = "max-h-64",
  autoScroll = true,
}: LiveLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isUserScrolling = useRef(false);
  const lastScrollTop = useRef(0);

  // When does this run and why?
  // Runs every time the logs array grows. If the user hasn't manually scrolled
  // up (browsing history), we auto-scroll to the newest entry.
  useEffect(() => {
    if (!autoScroll || isUserScrolling.current) return;
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs, autoScroll]);

  // What does this do? Detects if the user has manually scrolled up so we pause auto-scroll.
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    isUserScrolling.current = !atBottom;
    lastScrollTop.current = el.scrollTop;
  };

  return (
    <div className="rounded-lg border border-slate-800/60 bg-[#040b10] overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/60">
        <div className="flex items-center gap-2">
          {/* Terminal traffic lights */}
          <span className="w-2 h-2 rounded-full bg-red-600/60" />
          <span className="w-2 h-2 rounded-full bg-amber-500/60" />
          <span className="w-2 h-2 rounded-full bg-emerald-500/60" />
          <span className="ml-2 text-[9px] font-mono text-slate-600 uppercase tracking-widest">
            Swarm Log
          </span>
        </div>
        <span className="text-[9px] font-mono text-slate-700">
          {logs.length} line{logs.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Log body */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`${maxHeightClass} overflow-y-auto p-3 space-y-0.5 scroll-smooth`}
      >
        {logs.length === 0 ? (
          <p className="text-[11px] font-mono text-slate-700 select-none">
            Awaiting agent output...
          </p>
        ) : (
          logs.map((line) => <LogRow key={line.id} line={line} />)
        )}
      </div>

      {/* Bottom status strip */}
      {logs.length > 0 && (
        <div className="px-3 py-1.5 border-t border-slate-800/60 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
          <span className="text-[9px] font-mono text-cyan-700">Live</span>
        </div>
      )}
    </div>
  );
}
