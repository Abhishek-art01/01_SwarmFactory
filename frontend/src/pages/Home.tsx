/**
 * Home (page)
 *
 * The landing page of Swarm Factory.
 * Contains the RequirementInput form and the "launch" logic that:
 *  1. Calls POST /api/generate via the useJob hook
 *  2. Navigates to /dashboard/:job_id on success
 *
 * Visual goal: dark mission-control aesthetic with a central input panel
 * and a faint animated grid background to suggest a command terminal.
 */

import { Link, useNavigate } from "react-router-dom";
import { RequirementInput, SwarmOptions } from "../components/RequirementInput";
import { useJob } from "../hooks/useJob";
import { GenerateRequest } from "../lib/api";

// ─── Decorative background grid ───────────────────────────────────────────────

/**
 * GridBackground
 * A pure-CSS faint dot/line grid — no canvas, no animation library.
 */
function GridBackground() {
  return (
    <div
      className="pointer-events-none absolute inset-0 opacity-[0.04]"
      style={{
        backgroundImage: `
          linear-gradient(rgba(6,182,212,1) 1px, transparent 1px),
          linear-gradient(90deg, rgba(6,182,212,1) 1px, transparent 1px)
        `,
        backgroundSize: "48px 48px",
      }}
    />
  );
}

// ─── Stat pill ────────────────────────────────────────────────────────────────

/**
 * StatPill
 * A small decorative stat shown below the hero text.
 */
function StatPill({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col items-center">
      <span className="text-xl font-mono font-bold text-cyan-400">{value}</span>
      <span className="text-[10px] font-mono text-slate-600 uppercase tracking-widest">{label}</span>
    </div>
  );
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function Home() {
  const navigate = useNavigate();
  const { createJob, isCreating, createError } = useJob();

  /**
   * What does this do?
   * Bridges the RequirementInput's onSubmit to the API client,
   * then redirects to the live dashboard for that job.
   */
  const handleSubmit = async (requirement: string, options: SwarmOptions) => {
    const req: GenerateRequest = {
      requirement,
      options: {
        model: options.model,
        maxAgents: options.maxAgents,
        includeTests: options.includeTests,
        includeDocs: options.includeDocs,
      },
    };

    const jobId = await createJob(req);
    if (jobId) {
      navigate(`/dashboard/${jobId}`);
    }
  };

  return (
    <div className="relative min-h-screen bg-[#030810] flex flex-col items-center justify-center px-4 py-16 overflow-hidden">
      <GridBackground />

      {/* Radial glow behind the form */}
      <div
        className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] rounded-full opacity-10"
        style={{ background: "radial-gradient(ellipse, rgb(6,182,212) 0%, transparent 70%)" }}
      />

      {/* Logo / wordmark */}
      <div className="relative mb-10 text-center">
        <div className="flex items-center justify-center gap-3 mb-3">
          {/* Swarm icon: 7 dots */}
          <SwarmIcon />
          <h1 className="text-2xl font-mono font-bold text-slate-100 tracking-tight">
            Swarm<span className="text-cyan-400">Factory</span>
          </h1>
        </div>
        <p className="text-sm font-mono text-slate-500 max-w-md">
          Describe your software requirement. Seven AI agents build the complete codebase.
        </p>
      </div>

      {/* Stats row */}
      <div className="relative flex items-center gap-10 mb-8">
        <StatPill value="7"   label="Agents"   />
        <div className="w-px h-8 bg-slate-800" />
        <StatPill value="∞"   label="Stack"    />
        <div className="w-px h-8 bg-slate-800" />
        <StatPill value="RT"  label="Streaming" />
      </div>

      {/* Main input panel */}
      <div className="relative w-full">
        <RequirementInput onSubmit={handleSubmit} isLoading={isCreating} />
      </div>

      <Link
        to="/projects"
        className="relative mt-5 text-xs font-mono text-cyan-500 hover:text-cyan-300"
      >
        Open project chat history
      </Link>

      {/* API error bubble */}
      {createError && (
        <div className="relative mt-4 max-w-3xl mx-auto w-full px-4 py-3 rounded-lg border border-red-800/50 bg-red-950/40 text-xs font-mono text-red-400">
          <span className="font-bold">Error: </span>{createError}
        </div>
      )}

      {/* Footer */}
      <footer className="relative mt-16 text-[10px] font-mono text-slate-700 text-center">
        Swarm Factory — mission control for AI-generated code
      </footer>
    </div>
  );
}

// ─── SwarmIcon ────────────────────────────────────────────────────────────────

/**
 * SwarmIcon
 * Seven small dots arranged in a cluster to represent the agent swarm.
 */
function SwarmIcon() {
  // What does this do? Renders a purely decorative 7-dot swarm glyph.
  const positions = [
    [0, -10], [9, -5], [9, 5], [0, 10], [-9, 5], [-9, -5], [0, 0],
  ];
  return (
    <svg width="28" height="28" viewBox="-14 -14 28 28" className="flex-shrink-0">
      {positions.map(([cx, cy], i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={i === 6 ? 2.5 : 1.8}
          fill={i === 6 ? "rgb(6,182,212)" : "rgb(6,182,212)"}
          opacity={i === 6 ? 1 : 0.6}
        />
      ))}
    </svg>
  );
}
