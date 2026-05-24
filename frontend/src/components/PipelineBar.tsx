/**
 * PipelineBar
 *
 * A horizontal progress rail showing the 7 stages of the swarm pipeline.
 * Each stage is a node on the rail — completed stages glow green,
 * the active stage pulses cyan, and future stages are dim.
 *
 * The 7 canonical stages are defined here as a constant so they can be
 * reused across pages without repeating the labels.
 */

// ─── Stage definitions ────────────────────────────────────────────────────────

export interface PipelineStage {
  index: number;
  label: string;
  shortLabel: string;
}

export const PIPELINE_STAGES: PipelineStage[] = [
  { index: 0, label: "Requirements Analysis",  shortLabel: "Analyze"   },
  { index: 1, label: "Architecture Design",    shortLabel: "Architect" },
  { index: 2, label: "Code Generation",        shortLabel: "Generate"  },
  { index: 3, label: "Testing",                shortLabel: "Test"      },
  { index: 4, label: "Documentation",          shortLabel: "Docs"      },
  { index: 5, label: "Code Review",            shortLabel: "Review"    },
  { index: 6, label: "Deployment Prep",        shortLabel: "Deploy"    },
];

// ─── Props ────────────────────────────────────────────────────────────────────

interface PipelineBarProps {
  /** 0-based index of the currently active stage */
  activeIndex: number;
  /** Overall job completion 0-100 (drives the fill rail) */
  overallProgress: number;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

/**
 * StageNode
 * A single dot + label on the pipeline rail.
 */
function StageNode({
  stage,
  state,
}: {
  stage: PipelineStage;
  state: "done" | "active" | "pending";
}) {
  // What does this do? Renders a coloured dot and label for one pipeline stage.
  const dotClass =
    state === "done"
      ? "bg-emerald-500 ring-1 ring-emerald-400/40"
      : state === "active"
      ? "bg-cyan-400 ring-2 ring-cyan-400/30 animate-pulse"
      : "bg-slate-700 ring-1 ring-slate-600/30";

  const labelClass =
    state === "done"
      ? "text-emerald-400"
      : state === "active"
      ? "text-cyan-300 font-semibold"
      : "text-slate-600";

  return (
    <div className="flex flex-col items-center gap-1.5 flex-1 min-w-0">
      {/* Dot */}
      <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 transition-all duration-500 ${dotClass}`} />
      {/* Label (hidden on xs screens, use shortLabel) */}
      <span className={`text-[9px] font-mono text-center leading-tight truncate w-full px-1 ${labelClass}`}>
        <span className="hidden sm:block">{stage.shortLabel}</span>
        <span className="sm:hidden">{stage.index + 1}</span>
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function PipelineBar({ activeIndex, overallProgress }: PipelineBarProps) {
  // What does this do? Clamps progress to valid range and picks state per stage.
  const pct = Math.min(100, Math.max(0, overallProgress));

  return (
    <div className="w-full">
      {/* Progress fill rail */}
      <div className="relative">
        {/* Track */}
        <div className="absolute top-[4px] left-0 right-0 h-px bg-slate-800" />
        {/* Fill */}
        <div
          className="absolute top-[4px] left-0 h-px bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />

        {/* Stage nodes laid over the rail */}
        <div className="relative flex items-start">
          {PIPELINE_STAGES.map((stage) => {
            const state =
              stage.index < activeIndex
                ? "done"
                : stage.index === activeIndex
                ? "active"
                : "pending";
            return <StageNode key={stage.index} stage={stage} state={state} />;
          })}
        </div>
      </div>

      {/* Progress label */}
      <div className="flex items-center justify-between mt-2">
        <span className="text-[9px] font-mono text-slate-600 uppercase tracking-widest">
          Pipeline
        </span>
        <span className="text-[9px] font-mono text-cyan-600">
          {pct}% complete
        </span>
      </div>
    </div>
  );
}
