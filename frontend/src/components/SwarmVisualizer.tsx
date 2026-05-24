/**
 * SwarmVisualizer
 *
 * Renders the full grid of AgentCard components for all agents in the swarm.
 * Shows a placeholder skeleton grid when agents haven't loaded yet.
 * Clicking a card expands it to show the agent's current task detail.
 *
 * Accepts the `agents` array from useSwarm and renders each one.
 */

import { useState } from "react";
import { Agent } from "../lib/api";
import { AgentCard } from "./AgentCard";

// ─── Types ────────────────────────────────────────────────────────────────────

interface SwarmVisualizerProps {
  agents: Agent[];
  /** Show skeleton placeholders while agents are loading */
  isLoading?: boolean;
}

// ─── Skeleton placeholder ─────────────────────────────────────────────────────

/**
 * AgentSkeleton
 * A grey shimmer card shown before real agent data arrives.
 */
function AgentSkeleton() {
  // What does this do? Renders an animated placeholder card matching the AgentCard layout.
  return (
    <div className="rounded-lg border border-slate-800/60 p-3 bg-[#07111a] animate-pulse">
      <div className="flex items-center gap-2.5 mb-2.5">
        {/* Avatar placeholder */}
        <div className="w-8 h-8 rounded-full bg-slate-800 flex-shrink-0" />
        <div className="flex-1 space-y-1.5">
          <div className="h-2.5 bg-slate-800 rounded w-3/4" />
          <div className="h-2 bg-slate-800/60 rounded w-1/2" />
        </div>
        <div className="h-4 w-14 bg-slate-800 rounded" />
      </div>
      {/* Progress bar placeholder */}
      <div className="h-0.5 bg-slate-800 rounded-full" />
      <div className="h-2 bg-slate-800/40 rounded mt-2 w-1/3 ml-auto" />
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

/**
 * EmptySwarm
 * Shown when there are no agents yet and loading is false.
 */
function EmptySwarm() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="text-4xl mb-3 opacity-20 select-none">◎</div>
      <p className="text-xs font-mono text-slate-600 uppercase tracking-widest">
        Swarm not deployed
      </p>
      <p className="text-[11px] text-slate-700 mt-1">
        Submit a requirement to activate agents
      </p>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function SwarmVisualizer({ agents, isLoading = false }: SwarmVisualizerProps) {
  // Track which agent card is expanded (by agent id)
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // What does this do? Toggles the expanded card — clicking the same card collapses it.
  const handleCardClick = (agentId: string) => {
    setExpandedId((prev) => (prev === agentId ? null : agentId));
  };

  // Skeleton loading state
  if (isLoading && agents.length === 0) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <AgentSkeleton key={i} />
        ))}
      </div>
    );
  }

  // Empty state
  if (!isLoading && agents.length === 0) {
    return <EmptySwarm />;
  }

  return (
    <div className="space-y-3">
      {/* Summary row */}
      <div className="flex items-center gap-4 text-[10px] font-mono text-slate-600">
        <SummaryChip label="Total" count={agents.length} color="text-slate-500" />
        <SummaryChip
          label="Running"
          count={agents.filter((a) => a.status === "running").length}
          color="text-cyan-500"
        />
        <SummaryChip
          label="Done"
          count={agents.filter((a) => a.status === "done").length}
          color="text-emerald-500"
        />
        <SummaryChip
          label="Error"
          count={agents.filter((a) => a.status === "error").length}
          color="text-red-500"
        />
      </div>

      {/* Agent grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {agents.map((agent) => (
          <button
            key={agent.id}
            type="button"
            onClick={() => handleCardClick(agent.id)}
            className="text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-500 rounded-lg"
          >
            <AgentCard agent={agent} isExpanded={expandedId === agent.id} />
          </button>
        ))}
      </div>

      {/* Expanded detail panel */}
      {expandedId && (() => {
        const agent = agents.find((a) => a.id === expandedId);
        if (!agent) return null;
        return <AgentDetailPanel agent={agent} />;
      })()}
    </div>
  );
}

// ─── SummaryChip ─────────────────────────────────────────────────────────────

/**
 * SummaryChip
 * A small label + count inline in the header row.
 */
function SummaryChip({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <span>
      <span className={`${color} font-bold`}>{count}</span>{" "}
      <span className="text-slate-700">{label}</span>
    </span>
  );
}

// ─── AgentDetailPanel ────────────────────────────────────────────────────────

/**
 * AgentDetailPanel
 * An expanded info panel shown below the grid when a card is clicked.
 */
function AgentDetailPanel({ agent }: { agent: Agent }) {
  // What does this do? Shows the full task description, progress, and timestamp for one agent.
  return (
    <div className="rounded-lg border border-cyan-900/40 bg-[#050e15] p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-mono uppercase tracking-widest text-cyan-600">
          Agent Detail
        </span>
        <span className="text-[10px] font-mono text-slate-400">{agent.name}</span>
      </div>
      <p className="text-xs font-mono text-cyan-200">
        {agent.currentTask ?? "No active task"}
      </p>
      <div className="flex items-center justify-between text-[10px] font-mono text-slate-600">
        <span>Role: {agent.role}</span>
        <span>Updated: {new Date(agent.updatedAt).toLocaleTimeString()}</span>
      </div>
    </div>
  );
}
