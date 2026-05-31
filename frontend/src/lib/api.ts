/**
 * api.ts
 *
 * Typed HTTP client for the Swarm Factory backend.
 * Wraps every endpoint in a typed async function.
 * All errors are logged with the full response body before being re-thrown
 * so you can inspect them in the browser console.
 *
 * Base URL defaults to the same origin in production.
 * Override with the VITE_API_BASE_URL or VITE_API_URL env var during development:
 *   VITE_API_BASE_URL=http://localhost:8000
 */

// ─── Config ───────────────────────────────────────────────────────────────────

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.VITE_API_URL as string | undefined) ||
  "";

// ─── Domain types (mirrors backend contract) ──────────────────────────────────

export interface GenerateRequest {
  requirement: string;
  options: {
    model: string;
    maxAgents: number;
    includeTests: boolean;
    includeDocs: boolean;
  };
}

export interface GenerateResponse {
  job_id: string;
}

// ─── Agent status shapes ──────────────────────────────────────────────────────

export type AgentStatus = "idle" | "running" | "done" | "error";

export interface Agent {
  id: string;
  name: string;
  role: string;
  status: AgentStatus;
  /** Progress percentage 0-100 */
  progress: number;
  /** Human-readable description of current task */
  currentTask?: string;
  /** ISO timestamp of last update */
  updatedAt: string;
}

export interface JobStatus {
  job_id: string;
  stage: string;
  /** Index into the 7-stage pipeline (0-6) */
  stageIndex: number;
  agents: Agent[];
  /** Overall completion percentage */
  overallProgress: number;
  error?: string;
}

type RawJobStatus = {
  job_id: string;
  status?: string;
  progress?: {
    current_agent?: string;
    progress_pct?: number;
  } | null;
  error?: string | null;
};

// ─── Output shapes ────────────────────────────────────────────────────────────

export interface OutputFile {
  path: string;
  language: string;
  content: string;
  /** Size in bytes */
  size: number;
}

export interface JobOutput {
  job_id: string;
  files: OutputFile[];
  github_url: string;
  azure_url: string;
  /** Test coverage percentage 0-100 */
  coverage: number;
}

type RawJobOutput = {
  job_id: string;
  files?: Record<string, string> | OutputFile[] | null;
  github_url?: string | null;
  azure_url?: string | null;
  coverage?: number | null;
};

// ─── Internal helper ──────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number;
  statusText: string;
  body: unknown;
  path: string;

  constructor(path: string, response: Response, body: unknown) {
    super(`API ${response.status} ${response.statusText} from ${path}`);
    this.name = "ApiError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.body = body;
    this.path = path;
  }
}

/**
 * What does this do?
 * A thin fetch wrapper that adds JSON headers, checks for HTTP errors,
 * and re-throws with a readable message + logs the full error.
 */
async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const apiKey = import.meta.env.VITE_API_KEY as string | undefined;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(apiKey ? { "X-API-Key": apiKey } : {}),
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (networkErr) {
    console.error("API error: network failure →", networkErr);
    throw new Error(`Network error calling ${path}: ${String(networkErr)}`);
  }

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    console.error("API error:", {
      url,
      status: response.status,
      statusText: response.statusText,
      body,
    });
    throw new ApiError(path, response, body);
  }

  return response.json() as Promise<T>;
}

// ─── Public API functions ─────────────────────────────────────────────────────

const DEFAULT_AGENTS: Agent[] = [
  { id: "planner", name: "Planner", role: "Task graph", status: "idle", progress: 0, updatedAt: "" },
  { id: "architect", name: "Architect", role: "System design", status: "idle", progress: 0, updatedAt: "" },
  { id: "coder", name: "Coder", role: "Implementation", status: "idle", progress: 0, updatedAt: "" },
  { id: "test", name: "Test", role: "Test generation", status: "idle", progress: 0, updatedAt: "" },
  { id: "reviewer", name: "Reviewer", role: "Code review", status: "idle", progress: 0, updatedAt: "" },
  { id: "mediator", name: "Mediator", role: "Merge outputs", status: "idle", progress: 0, updatedAt: "" },
  { id: "devops", name: "DevOps", role: "Publish artifacts", status: "idle", progress: 0, updatedAt: "" },
];

const STAGE_INDEX: Record<string, number> = {
  queued: 0,
  planner: 0,
  architect: 1,
  "coder+test+reviewer": 2,
  coder: 2,
  test: 2,
  reviewer: 2,
  mediator: 3,
  devops: 4,
  complete: 6,
  failed: 6,
};

function normalizeJobStatus(raw: RawJobStatus): JobStatus {
  const currentAgent = raw.progress?.current_agent || raw.status || "queued";
  const overallProgress = raw.progress?.progress_pct ?? (raw.status === "complete" ? 100 : 0);
  const now = new Date().toISOString();
  const activeAgents = new Set(currentAgent.split("+"));

  return {
    job_id: raw.job_id,
    stage: currentAgent,
    stageIndex: STAGE_INDEX[currentAgent] ?? STAGE_INDEX[raw.status ?? "queued"] ?? 0,
    overallProgress,
    agents: DEFAULT_AGENTS.map((agent) => ({
      ...agent,
      status:
        raw.status === "complete"
          ? "done"
          : raw.status === "failed"
            ? "error"
            : activeAgents.has(agent.id)
              ? "running"
              : "idle",
      progress: activeAgents.has(agent.id) ? overallProgress : agent.progress,
      updatedAt: now,
    })),
    error: raw.error ?? undefined,
  };
}

function inferLanguage(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase();
  switch (extension) {
    case "py":
      return "python";
    case "ts":
    case "tsx":
      return "typescript";
    case "js":
    case "jsx":
      return "javascript";
    case "json":
      return "json";
    case "md":
      return "markdown";
    case "txt":
      return "text";
    default:
      return extension || "plaintext";
  }
}

function normalizeJobOutput(raw: RawJobOutput): JobOutput {
  const files = Array.isArray(raw.files)
    ? raw.files
    : Object.entries(raw.files ?? {}).map(([path, content]) => ({
        path,
        content,
        language: inferLanguage(path),
        size: new Blob([content]).size,
      }));

  return {
    job_id: raw.job_id,
    files,
    github_url: raw.github_url ?? "",
    azure_url: raw.azure_url ?? "",
    coverage: raw.coverage ?? 0,
  };
}

/**
 * What does this do?
 * Sends the user's plain-English requirement to the backend to kick off
 * the swarm pipeline. Returns a job_id used for all subsequent polling.
 *
 * POST /api/generate
 */
export async function generateJob(payload: GenerateRequest): Promise<GenerateResponse> {
  return apiFetch<GenerateResponse>("/api/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * What does this do?
 * Polls the job status — stage name, agent states, overall progress.
 * Call this on a timer as a fallback when the WebSocket is unavailable.
 *
 * GET /api/status/:job_id
 */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const raw = await apiFetch<RawJobStatus>(`/api/status/${jobId}`);
  return normalizeJobStatus(raw);
}

/**
 * What does this do?
 * Fetches the completed output once the job has finished —
 * the generated file tree, GitHub URL, Azure URL, and test coverage.
 *
 * GET /api/output/:job_id
 */
export async function getJobOutput(jobId: string): Promise<JobOutput> {
  const raw = await apiFetch<RawJobOutput>(`/api/output/${jobId}`);
  return normalizeJobOutput(raw);
}
