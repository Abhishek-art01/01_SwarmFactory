/**
 * Dashboard (page)
 *
 * The live "mission control" view for an active swarm job.
 * Reads the :jobId param from the URL, subscribes to real-time WebSocket
 * updates via useSwarm, and lays out:
 *
 *   ┌─────────────────────────────────────────────────┐
 *   │  MetricsBar (top strip)                          │
 *   │  PipelineBar (stage rail)                        │
 *   ├──────────────────────┬──────────────────────────┤
 *   │  SwarmVisualizer     │  LiveLog                 │
 *   │  (agent grid)        │  FileTree                │
 *   └──────────────────────┴──────────────────────────┘
 *
 * When the job completes, a banner appears with a link to the Output page.
 */

import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useSwarm } from "../hooks/useSwarm";
import { SwarmVisualizer } from "../components/SwarmVisualizer";
import { PipelineBar } from "../components/PipelineBar";
import { LiveLog } from "../components/LiveLog";
import { FileTree } from "../components/FileTree";
import { MetricsBar } from "../components/MetricsBar";

// ─── Page component ───────────────────────────────────────────────────────────

export default function Dashboard() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const swarm = useSwarm(jobId ?? null);
  const startedAt = useRef<string>(new Date().toISOString());

  // What does this do? Tracks which file path was selected in the FileTree.
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  // When does this run and why?
  // If no jobId is present in the URL, we redirect home so the user can
  // submit a new requirement rather than seeing a broken dashboard.
  useEffect(() => {
    if (!jobId) {
      navigate("/", { replace: true });
    }
  }, [jobId, navigate]);

  // When does this run and why?
  // Once the swarm signals completion we wait 1.5 s then scroll the
  // completion banner into view so the user notices it.
  const bannerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!swarm.isComplete) return;
    const t = setTimeout(() => {
      bannerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 1500);
    return () => clearTimeout(t);
  }, [swarm.isComplete]);

  const activeAgentCount = (swarm.agents ?? []).filter((a) => a.status === "running").length;

  if (!jobId) return null;

  return (
    <div className="min-h-screen bg-[#030810] text-slate-100">
      {/* Top nav bar */}
      <NavBar jobId={jobId} isComplete={swarm.isComplete} />

      <div className="max-w-[1400px] mx-auto px-4 py-4 space-y-4">

        {/* Metrics strip */}
        <MetricsBar
          startedAt={startedAt.current}
          fileCount={swarm.files.length}
          activeAgentCount={activeAgentCount}
          overallProgress={swarm.overallProgress}
          wsState={swarm.wsState}
          coverage={null}
        />

        {/* Pipeline rail */}
        <div className="rounded-lg border border-slate-800/60 bg-[#070e17] px-5 py-4">
          <PipelineBar
            activeIndex={swarm.stageIndex}
            overallProgress={swarm.overallProgress}
          />
        </div>

        {/* Completion banner */}
        {swarm.isComplete && (
          <div
            ref={bannerRef}
            className="rounded-lg border border-emerald-700/50 bg-emerald-950/40 px-5 py-4 flex items-center justify-between"
          >
            <div className="flex items-center gap-3">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className="text-sm font-mono text-emerald-300 font-semibold">
                Swarm job complete
              </span>
              <span className="text-xs font-mono text-emerald-700">
                {swarm.files.length} files generated
              </span>
            </div>
            <Link
              to={`/output/${jobId}`}
              className="px-4 py-1.5 rounded-lg text-xs font-mono border border-emerald-600/50 bg-emerald-900/30 text-emerald-300 hover:bg-emerald-800/40 transition-colors"
            >
              View Output →
            </Link>
          </div>
        )}

        {/* Error banner */}
        {swarm.error && (
          <div className="rounded-lg border border-red-800/50 bg-red-950/30 px-5 py-3 flex items-center gap-3">
            <span className="text-red-400 text-sm font-mono font-bold">Error</span>
            <span className="text-xs font-mono text-red-300">{swarm.error}</span>
          </div>
        )}

        {/* Main two-column layout */}
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-4">

          {/* Left: agent visualizer */}
          <div className="space-y-4">
            <SectionLabel>Agent Swarm</SectionLabel>
            <SwarmVisualizer
              agents={swarm.agents ?? []}
              isLoading={(swarm.agents ?? []).length === 0 && !swarm.isComplete}
            />
          </div>

          {/* Right: log + file tree */}
          <div className="space-y-4">
            <SectionLabel>Live Output</SectionLabel>
            <LiveLog logs={swarm.logs} maxHeightClass="max-h-72" />
            <FileTree
              files={swarm.files}
              onFileSelect={setSelectedFile}
            />
            {selectedFile && (
              <p className="text-[10px] font-mono text-cyan-600 truncate px-1">
                Selected: {selectedFile} — view full content on the Output page
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── NavBar ───────────────────────────────────────────────────────────────────

/**
 * NavBar
 * Top navigation strip with branding, job id, and a link to output.
 */
function NavBar({ jobId, isComplete }: { jobId: string; isComplete: boolean }) {
  return (
    <div className="sticky top-0 z-10 border-b border-slate-800/60 bg-[#030810]/90 backdrop-blur-sm">
      <div className="max-w-[1400px] mx-auto px-4 h-12 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="text-sm font-mono font-bold text-slate-300 hover:text-cyan-400 transition-colors"
          >
            Swarm<span className="text-cyan-400">Factory</span>
          </Link>
          <span className="text-[9px] font-mono text-slate-700 uppercase tracking-widest">
            Dashboard
          </span>
          <span className="text-[10px] font-mono text-slate-600 hidden sm:block">
            {jobId}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {isComplete && (
            <Link
              to={`/output/${jobId}`}
              className="text-[10px] font-mono text-emerald-400 border border-emerald-800/50 px-3 py-1 rounded hover:bg-emerald-900/20 transition-colors"
            >
              View Output
            </Link>
          )}
          <Link
            to="/"
            className="text-[10px] font-mono text-slate-600 hover:text-slate-400 transition-colors"
          >
            ← New Job
          </Link>
        </div>
      </div>
    </div>
  );
}

// ─── SectionLabel ─────────────────────────────────────────────────────────────

/**
 * SectionLabel
 * A small uppercase label used as a section heading inside the dashboard grid.
 */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[9px] font-mono text-slate-600 uppercase tracking-[0.2em]">
      {children}
    </p>
  );
}
