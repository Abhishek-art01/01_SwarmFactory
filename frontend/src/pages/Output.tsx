/**
 * Output (page)
 *
 * The final results page shown after the swarm completes.
 * Fetches the job output from GET /api/output/:jobId and displays:
 *  - Coverage score + deployment URLs (GitHub, Azure)
 *  - FileTree for browsing generated files
 *  - CodeViewer for reading any selected file
 *
 * Layout:
 *   ┌────────────────────────────────────────────────┐
 *   │  Outcome strip (coverage, GitHub, Azure)        │
 *   ├──────────────────┬─────────────────────────────┤
 *   │  FileTree        │  CodeViewer                  │
 *   └──────────────────┴─────────────────────────────┘
 */

import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useJob } from "../hooks/useJob";
import { OutputFile, JobOutput } from "../lib/api";
import { FileTree } from "../components/FileTree";
import { CodeViewer } from "../components/CodeViewer";
import { WrittenFile } from "../hooks/useSwarm";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * What does this do?
 * Converts OutputFile[] (from the API) to WrittenFile[] (used by FileTree).
 * The shapes are similar but come from different layers of the app.
 */
function toWrittenFiles(files: OutputFile[]): WrittenFile[] {
  return files.map((f) => ({
    path: f.path,
    language: f.language,
    size: f.size,
    agent: "swarm",
    writtenAt: new Date().toISOString(),
  }));
}

// ─── Sub-components ───────────────────────────────────────────────────────────

/**
 * OutcomeStrip
 * Top-of-page summary row: coverage badge + deployment URLs.
 */
function OutcomeStrip({ output }: { output: JobOutput }) {
  const coverageColor =
    output.coverage >= 80
      ? "text-emerald-400 border-emerald-700/50 bg-emerald-950/40"
      : output.coverage >= 60
      ? "text-amber-400 border-amber-700/50 bg-amber-950/40"
      : "text-red-400 border-red-700/50 bg-red-950/40";

  return (
    <div className="rounded-lg border border-slate-800/60 bg-[#070e17] px-5 py-4 flex flex-wrap items-center gap-5">
      {/* Coverage */}
      <div className={`flex items-center gap-2 px-3 py-1.5 rounded border font-mono text-sm ${coverageColor}`}>
        <span className="text-[9px] uppercase tracking-widest opacity-60">Coverage</span>
        <span className="font-bold">{output.coverage}%</span>
      </div>

      {/* File count */}
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-mono uppercase tracking-widest text-slate-600">Files</span>
        <span className="text-sm font-mono font-bold text-slate-300">{output.files.length}</span>
      </div>

      <div className="flex-1" />

      {/* GitHub link */}
      {output.github_url && (
        <DeployLink href={output.github_url} label="GitHub" color="text-slate-300" />
      )}

      {/* Azure link */}
      {output.azure_url && (
        <DeployLink href={output.azure_url} label="Azure" color="text-sky-400" />
      )}
    </div>
  );
}

/**
 * DeployLink
 * An external-link button for GitHub / Azure deploy targets.
 */
function DeployLink({ href, label, color }: { href: string; label: string; color: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded border border-slate-700/50 bg-slate-900/40 text-xs font-mono hover:bg-slate-800/60 transition-colors ${color}`}
    >
      <span>{label}</span>
      <span className="text-[10px] opacity-50">↗</span>
    </a>
  );
}

/**
 * EmptyViewer
 * Shown in the CodeViewer pane before the user selects a file.
 */
function EmptyViewer() {
  return (
    <div className="flex flex-col items-center justify-center h-64 rounded-lg border border-slate-800/60 bg-[#040b10] text-center">
      <span className="text-3xl opacity-10 select-none mb-3">{ }</span>
      <p className="text-xs font-mono text-slate-600">Select a file to view its contents</p>
    </div>
  );
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function Output() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { output, isFetchingOutput, outputError, fetchOutput } = useJob();
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  // When does this run and why?
  // Fires once on mount to load the job output. Redirects home if jobId is missing.
  useEffect(() => {
    if (!jobId) {
      navigate("/", { replace: true });
      return;
    }
    void fetchOutput(jobId);
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // What does this do? Finds the full OutputFile record for the selected path.
  const selectedFile: OutputFile | undefined = output?.files.find(
    (f) => f.path === selectedPath
  );

  // ── Loading state ────────────────────────────────────────────────────────────
  if (isFetchingOutput) {
    return (
      <PageShell jobId={jobId ?? ""}>
        <div className="flex items-center justify-center py-32">
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="w-6 h-6 border-2 border-cyan-500/30 border-t-cyan-400 rounded-full animate-spin" />
            <p className="text-xs font-mono text-slate-600">Loading output...</p>
          </div>
        </div>
      </PageShell>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────────
  if (outputError) {
    return (
      <PageShell jobId={jobId ?? ""}>
        <div className="rounded-lg border border-red-800/50 bg-red-950/30 px-5 py-6 text-center space-y-2">
          <p className="text-sm font-mono text-red-400 font-bold">Failed to load output</p>
          <p className="text-xs font-mono text-red-700">{outputError}</p>
          <button
            type="button"
            onClick={() => jobId && void fetchOutput(jobId)}
            className="mt-2 px-4 py-1.5 text-xs font-mono border border-red-700/40 text-red-400 rounded hover:bg-red-900/20 transition-colors"
          >
            Retry
          </button>
        </div>
      </PageShell>
    );
  }

  // ── Empty / not ready ────────────────────────────────────────────────────────
  if (!output) {
    return (
      <PageShell jobId={jobId ?? ""}>
        <div className="py-24 text-center">
          <p className="text-sm font-mono text-slate-600">No output available yet.</p>
          <Link
            to={`/dashboard/${jobId}`}
            className="mt-4 inline-block text-xs font-mono text-cyan-600 hover:text-cyan-400"
          >
            ← Back to Dashboard
          </Link>
        </div>
      </PageShell>
    );
  }

  // ── Success ──────────────────────────────────────────────────────────────────
  const writtenFiles = toWrittenFiles(output.files);

  return (
    <PageShell jobId={jobId ?? ""}>
      <OutcomeStrip output={output} />

      {/* Two-column: tree + viewer */}
      <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-4 mt-4">
        {/* File tree */}
        <div>
          <p className="text-[9px] font-mono text-slate-600 uppercase tracking-widest mb-2">
            Generated Files
          </p>
          <FileTree
            files={writtenFiles}
            onFileSelect={setSelectedPath}
          />
        </div>

        {/* Code viewer */}
        <div>
          <p className="text-[9px] font-mono text-slate-600 uppercase tracking-widest mb-2">
            {selectedPath ?? "Code Viewer"}
          </p>
          {selectedFile ? (
            <CodeViewer
              path={selectedFile.path}
              content={selectedFile.content}
              language={selectedFile.language}
            />
          ) : (
            <EmptyViewer />
          )}
        </div>
      </div>
    </PageShell>
  );
}

// ─── PageShell ────────────────────────────────────────────────────────────────

/**
 * PageShell
 * Shared chrome (nav bar + page wrapper) for all Output page states.
 */
function PageShell({ jobId, children }: { jobId: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#030810] text-slate-100">
      {/* Nav */}
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
              Output
            </span>
            <span className="text-[10px] font-mono text-slate-600 hidden sm:block">
              {jobId}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to={`/dashboard/${jobId}`}
              className="text-[10px] font-mono text-slate-600 hover:text-slate-400 transition-colors"
            >
              ← Dashboard
            </Link>
            <Link
              to="/"
              className="text-[10px] font-mono text-slate-600 hover:text-slate-400 transition-colors"
            >
              New Job
            </Link>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-[1400px] mx-auto px-4 py-6 space-y-4">
        {children}
      </div>
    </div>
  );
}
