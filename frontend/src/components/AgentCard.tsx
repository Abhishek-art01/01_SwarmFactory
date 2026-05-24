/**
 * AgentCard
 *
 * Displays the status of a single AI agent in the swarm.
 * Shows the agent's name, role, current task, progress bar,
 * and a colour-coded status badge (idle / running / done / error).
 *
 * Status colours:
 *  idle    → slate / dim
 *  running → cyan (animated pulse)
 *  done    → emerald
 *  error   → red
 */

import { Agent, AgentStatus } from "../lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AgentCardProps {
  agent: Agent;
  /** If true, expands the card to show more detail */
  isExpanded?: boolean;
}

// ─── Status style maps ────────────────────────────────────────────────────────

const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: "IDLE",
  running: "RUNNING",
  done: "DONE",
  error: "ERROR",
};

const STATUS_BORDER: Record<AgentStatus, string> = {
  idle: "border-slate-700/50",
  running: "border-cyan-500/60",
  done: "border-emerald-500/50",
  error: "border-red-500/60",
};

const STATUS_GLOW: Record<AgentStatus, string> = {
  idle: "",
  running: "shadow-[0_0_16px_rgba(6,182,212,0.12)]",
  done: "shadow-[0_0_12px_rgba(16,185,129,0.10)]",
  error: "shadow-[0_0_14px_rgba(239,68,68,0.14)]",
};

const STATUS_BADGE_BG: Record<AgentStatus, string> = {
  idle: "bg-slate-800 text-slate-500",
  running: "bg-cyan-900/60 text-cyan-300",
  done: "bg-emerald-900/60 text-emerald-300",
  error: "bg-red-900/60 text-red-400",
};

const STATUS_BAR_COLOR: Record<AgentStatus, string> = {
  idle: "bg-slate-600",
  running: "bg-cyan-400",
  done: "bg-emerald-400",
  error: "bg-red-500",
};

// ─── Helper: status dot ───────────────────────────────────────────────────────

/**
 * StatusDot
 * Animated indicator dot next to the badge text.
 */
function StatusDot({ status }: { status: AgentStatus }) {
  const base = "w-1.5 h-1.5 rounded-full flex-shrink-0";
  if (status === "running") {
    return <span className={`${base} bg-cyan-400 animate-pulse`} />;
  }
  const color: Record<AgentStatus, string> = {
    idle: "bg-slate-600",
    running: "bg-cyan-400",
    done: "bg-emerald-400",
    error: "bg-red-500",
  };
  return <span className={`${base} ${color[status]}`} />;
}

// ─── Helper: progress bar ────────────────────────────────────────────────────

/**
 * ProgressBar
 * A thin horizontal bar showing agent progress (0-100).
 */
function ProgressBar({ progress, status }: { progress: number; status: AgentStatus }) {
  // What does this do? Clamps progress to 0-100 and renders a coloured fill bar.
  const clamped = Math.min(100, Math.max(0, progress));
  return (
    <div className="h-0.5 w-full bg-slate-800 rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-700 ease-out ${STATUS_BAR_COLOR[status]}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

// ─── Agent icon (emoji-free, text-based) ─────────────────────────────────────

/**
 * AgentIcon
 * A monogram circle derived from the agent's name initials.
 */
function AgentIcon({ name, status }: { name: string; status: AgentStatus }) {
  // What does this do? Extracts up to two initials from the agent name for the avatar.
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

  const ringColor: Record<AgentStatus, string> = {
    idle: "ring-slate-700",
    running: "ring-cyan-500",
    done: "ring-emerald-500",
    error: "ring-red-500",
  };

  return (
    <div
      className={`w-8 h-8 rounded-full ring-1 flex items-center justify-center text-[10px] font-mono font-bold bg-slate-900 flex-shrink-0
        ${ringColor[status]}`}
    >
      <span className={status === "running" ? "text-cyan-300" : "text-slate-400"}>
        {initials}
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function AgentCard({ agent, isExpanded = false }: AgentCardProps) {
  const { name, role, status, progress, currentTask } = agent;

  return (
    <div
      className={`rounded-lg border p-3 bg-[#07111a] transition-all duration-300
        ${STATUS_BORDER[status]}
        ${STATUS_GLOW[status]}`}
    >
      {/* Header row */}
      <div className="flex items-center gap-2.5 mb-2.5">
        <AgentIcon name={name} status={status} />

        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono font-semibold text-slate-200 truncate">{name}</p>
          <p className="text-[10px] text-slate-500 truncate">{role}</p>
        </div>

        {/* Status badge */}
        <span
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-mono tracking-widest flex-shrink-0
            ${STATUS_BADGE_BG[status]}`}
        >
          <StatusDot status={status} />
          {STATUS_LABEL[status]}
        </span>
      </div>

      {/* Progress bar */}
      <ProgressBar progress={progress} status={status} />

      {/* Progress % */}
      <div className="flex items-center justify-between mt-1.5">
        <span className="text-[10px] font-mono text-slate-600">
          {isExpanded && currentTask ? (
            <span className="text-slate-400 truncate block max-w-[180px]">{currentTask}</span>
          ) : (
            <span>&nbsp;</span>
          )}
        </span>
        <span className="text-[10px] font-mono text-slate-500">{progress}%</span>
      </div>
    </div>
  );
}
