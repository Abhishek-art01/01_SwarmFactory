/**
 * RequirementInput
 *
 * The main entry point for the Swarm Factory UI.
 * Renders a large textarea where the user types their software requirement in plain English,
 * along with an optional model/options selector and a "Launch Swarm" submit button.
 *
 * On submit it calls `onSubmit(requirement, options)` provided by the parent page.
 * Handles loading (disables the form while the job is being created) and
 * validation (prevents empty submissions).
 */

import { useState, useRef, KeyboardEvent } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SwarmOptions {
  model: "gpt-4o" | "phi-4" | "gpt-4o-mini";
  maxAgents: number;
  includeTests: boolean;
  includeDocs: boolean;
}

interface RequirementInputProps {
  /** Called when the user submits a valid requirement */
  onSubmit: (requirement: string, options: SwarmOptions) => Promise<void>;
  /** Whether the form should be locked (job is being created) */
  isLoading?: boolean;
}

// ─── Default options ──────────────────────────────────────────────────────────

const DEFAULT_OPTIONS: SwarmOptions = {
  model: "gpt-4o",
  maxAgents: 7,
  includeTests: true,
  includeDocs: true,
};

// ─── Sub-component: Options Panel ────────────────────────────────────────────

/**
 * OptionsPanel
 * Collapsible row of configuration toggles shown beneath the textarea.
 */
function OptionsPanel({
  options,
  onChange,
  disabled,
}: {
  options: SwarmOptions;
  onChange: (next: SwarmOptions) => void;
  disabled: boolean;
}) {
  // What does this do? Renders a row of small toggle/select controls for swarm config.
  return (
    <div className="flex flex-wrap items-center gap-4 pt-3 border-t border-cyan-900/40">
      {/* Model selector */}
      <label className="flex items-center gap-2 text-xs text-cyan-400/70">
        <span className="font-mono uppercase tracking-widest">Model</span>
        <select
          disabled={disabled}
          value={options.model}
          onChange={(e) =>
            onChange({ ...options, model: e.target.value as SwarmOptions["model"] })
          }
          className="bg-black/60 border border-cyan-800/50 text-cyan-200 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-cyan-500 disabled:opacity-40"
        >
          <option value="gpt-4o">GPT-4o</option>
          <option value="phi-4">Phi-4</option>
          <option value="gpt-4o-mini">GPT-4o-mini</option>
        </select>
      </label>

      {/* Tests toggle */}
      <ToggleChip
        label="Tests"
        active={options.includeTests}
        disabled={disabled}
        onToggle={() => onChange({ ...options, includeTests: !options.includeTests })}
      />

      {/* Docs toggle */}
      <ToggleChip
        label="Docs"
        active={options.includeDocs}
        disabled={disabled}
        onToggle={() => onChange({ ...options, includeDocs: !options.includeDocs })}
      />

      {/* Agent count */}
      <label className="flex items-center gap-2 text-xs text-cyan-400/70 ml-auto">
        <span className="font-mono uppercase tracking-widest">Agents</span>
        <select
          disabled={disabled}
          value={options.maxAgents}
          onChange={(e) =>
            onChange({ ...options, maxAgents: Number(e.target.value) })
          }
          className="bg-black/60 border border-cyan-800/50 text-cyan-200 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-cyan-500 disabled:opacity-40"
        >
          {[3, 5, 7].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/**
 * ToggleChip
 * A small pill button that toggles a boolean option on/off.
 */
function ToggleChip({
  label,
  active,
  disabled,
  onToggle,
}: {
  label: string;
  active: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  // What does this do? Renders an active/inactive pill for a boolean config option.
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onToggle}
      className={`px-3 py-1 rounded-full text-xs font-mono tracking-wider border transition-all duration-200 disabled:opacity-40
        ${
          active
            ? "bg-cyan-500/20 border-cyan-500/60 text-cyan-300"
            : "bg-transparent border-cyan-900/50 text-cyan-700 hover:border-cyan-700/60"
        }`}
    >
      {active ? "✓ " : ""}{label}
    </button>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function RequirementInput({ onSubmit, isLoading = false }: RequirementInputProps) {
  const [requirement, setRequirement] = useState("");
  const [options, setOptions] = useState<SwarmOptions>(DEFAULT_OPTIONS);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // What does this do? Validates the form then delegates to the parent's onSubmit handler.
  const handleSubmit = async () => {
    const trimmed = requirement.trim();
    if (!trimmed) {
      setError("Please describe what you want to build.");
      textareaRef.current?.focus();
      return;
    }
    if (trimmed.length < 20) {
      setError("Be more specific — describe the full requirement (min 20 chars).");
      return;
    }
    setError(null);
    try {
      await onSubmit(trimmed, options);
    } catch (err) {
      console.error("API error:", err);
      setError("Failed to launch swarm. Check the console for details.");
    }
  };

  // What does this do? Allows Cmd/Ctrl+Enter to submit without clicking the button.
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      handleSubmit();
    }
  };

  const charCount = requirement.length;
  const isOverLimit = charCount > 2000;

  return (
    <div className="w-full max-w-3xl mx-auto">
      {/* Panel */}
      <div
        className={`relative rounded-xl border transition-colors duration-300
          ${isLoading ? "border-cyan-500/40 shadow-[0_0_30px_rgba(6,182,212,0.08)]" : "border-cyan-900/50 hover:border-cyan-700/60"}
          bg-[#060d14]/90 backdrop-blur-sm`}
      >
        {/* Scanning line animation while loading */}
        {isLoading && (
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-400 to-transparent animate-pulse" />
        )}

        <div className="p-5 space-y-4">
          {/* Label row */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono tracking-[0.2em] text-cyan-500/60 uppercase">
              Mission Briefing
            </span>
            <span
              className={`text-[10px] font-mono ${
                isOverLimit ? "text-red-400" : "text-cyan-700"
              }`}
            >
              {charCount} / 2000
            </span>
          </div>

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={requirement}
            onChange={(e) => {
              setRequirement(e.target.value);
              if (error) setError(null);
            }}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={5}
            placeholder={
              "Describe the software you want the swarm to build...\n\nExample: Build a REST API in FastAPI that manages a to-do list with user authentication, PostgreSQL persistence, and a React frontend with dark mode."
            }
            className="w-full bg-transparent text-cyan-100 placeholder-cyan-900/60 font-mono text-sm leading-relaxed resize-none focus:outline-none disabled:opacity-50"
          />

          {/* Options */}
          <OptionsPanel options={options} onChange={setOptions} disabled={isLoading} />

          {/* Error message */}
          {error && (
            <p className="text-xs font-mono text-red-400 flex items-center gap-2">
              <span className="text-red-500">▲</span> {error}
            </p>
          )}

          {/* Submit row */}
          <div className="flex items-center justify-between pt-1">
            <span className="text-[10px] text-cyan-800 font-mono">
              ⌘ + Enter to launch
            </span>
            <LaunchButton onClick={handleSubmit} isLoading={isLoading} disabled={isOverLimit} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── LaunchButton ─────────────────────────────────────────────────────────────

/**
 * LaunchButton
 * The primary CTA. Shows a spinner while the job creation request is in-flight.
 */
function LaunchButton({
  onClick,
  isLoading,
  disabled,
}: {
  onClick: () => void;
  isLoading: boolean;
  disabled: boolean;
}) {
  // What does this do? Renders the submit button with an animated loading state.
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isLoading || disabled}
      className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-mono tracking-wider transition-all duration-200
        ${
          isLoading || disabled
            ? "bg-cyan-900/30 border border-cyan-800/30 text-cyan-700 cursor-not-allowed"
            : "bg-cyan-500/10 border border-cyan-500/50 text-cyan-300 hover:bg-cyan-500/20 hover:border-cyan-400 active:scale-95"
        }`}
    >
      {isLoading ? (
        <>
          <SpinnerIcon />
          Launching...
        </>
      ) : (
        <>
          <span className="text-cyan-500">▶</span>
          Launch Swarm
        </>
      )}
    </button>
  );
}

/** Inline SVG spinner — no external dependency needed */
function SpinnerIcon() {
  return (
    <svg
      className="animate-spin"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" />
    </svg>
  );
}
