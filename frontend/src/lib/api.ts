/**
 * api.ts
 *
 * Typed HTTP client for the Swarm Factory backend.
 * Wraps every endpoint in a typed async function.
 * All errors are logged with the full response body before being re-thrown
 * so you can inspect them in the browser console.
 *
 * Base URL defaults to the same origin in production.
 * Override with the VITE_API_BASE_URL env var during development:
 *   VITE_API_BASE_URL=http://localhost:8000
 */

// ─── Config ───────────────────────────────────────────────────────────────────

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

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

// ─── Internal helper ──────────────────────────────────────────────────────────

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

  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
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
    throw new Error(
      `API ${response.status} ${response.statusText} from ${path}`
    );
  }

  return response.json() as Promise<T>;
}

// ─── Public API functions ─────────────────────────────────────────────────────

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
  return apiFetch<JobStatus>(`/api/status/${jobId}`);
}

/**
 * What does this do?
 * Fetches the completed output once the job has finished —
 * the generated file tree, GitHub URL, Azure URL, and test coverage.
 *
 * GET /api/output/:job_id
 */
export async function getJobOutput(jobId: string): Promise<JobOutput> {
  return apiFetch<JobOutput>(`/api/output/${jobId}`);
}
