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

export interface Project {
  id: string;
  user_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  default_workspace_id?: string;
}

export interface Workspace {
  id: string;
  project_id: string;
  user_id: string;
  name: string;
  storage_key: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  workspaces: Workspace[];
}

export interface Conversation {
  id: string;
  project_id: string;
  workspace_id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived?: boolean;
}

export type MessageRole = "user" | "assistant" | "system" | "agent";

export interface ChatMessage {
  id: string;
  conversation_id: string;
  project_id: string;
  workspace_id: string;
  user_id: string;
  role: MessageRole;
  content: string;
  agent_name?: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface CreateMessageResponse {
  message: ChatMessage;
  assistant_message?: ChatMessage;
}

export interface ContextMessage {
  id: string;
  role: MessageRole;
  content: string;
  agent_name?: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface ProjectContext {
  project: Record<string, unknown>;
  workspace: Record<string, unknown>;
  conversation: Record<string, unknown>;
  recent_messages: ContextMessage[];
  relevant_messages: ContextMessage[];
  summary: string;
  file_tree: Array<Record<string, unknown>>;
  known_limitations: string[];
  next_recommended_actions: string[];
}

export interface WorkspaceFile {
  id: string;
  project_id: string;
  workspace_id: string;
  user_id: string;
  path: string;
  name: string;
  language: string;
  size: number;
  hash: string;
  content_blob_name: string;
  created_at: string;
  updated_at: string;
}

export interface FileTreeNode {
  name: string;
  path: string;
  type: "directory" | "file";
  children?: FileTreeNode[];
  language?: string;
  size?: number;
  hash?: string;
  updated_at?: string;
}

export interface FileTreeResponse {
  workspace_id: string;
  files: WorkspaceFile[];
  tree: FileTreeNode[];
}

export interface FileContentResponse {
  file: WorkspaceFile;
  content: string;
  truncated: boolean;
  redacted: boolean;
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

export async function listProjects(): Promise<Project[]> {
  return apiFetch<Project[]>("/api/projects");
}

export async function createProject(payload: { name: string; description?: string }): Promise<Project> {
  return apiFetch<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${projectId}`);
}

export async function listConversations(projectId: string): Promise<Conversation[]> {
  return apiFetch<Conversation[]>(`/api/projects/${projectId}/conversations`);
}

export async function createConversation(
  projectId: string,
  payload: { workspace_id?: string; title?: string } = {}
): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/projects/${projectId}/conversations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getLatestConversation(projectId: string): Promise<Conversation | null> {
  return apiFetch<Conversation | null>(`/api/projects/${projectId}/conversations/latest`);
}

export async function getConversationMessages(conversationId: string): Promise<ChatMessage[]> {
  return apiFetch<ChatMessage[]>(`/api/conversations/${conversationId}/messages`);
}

export async function getProjectContext(projectId: string, conversationId: string): Promise<ProjectContext> {
  return apiFetch<ProjectContext>(`/api/projects/${projectId}/conversations/${conversationId}/context`);
}

export async function getWorkspaceFileTree(projectId: string, workspaceId: string): Promise<FileTreeResponse> {
  return apiFetch<FileTreeResponse>(`/api/projects/${projectId}/workspaces/${workspaceId}/files/tree`);
}

export async function getWorkspaceFileContent(
  projectId: string,
  workspaceId: string,
  path: string
): Promise<FileContentResponse> {
  return apiFetch<FileContentResponse>(
    `/api/projects/${projectId}/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(path)}`
  );
}

export async function saveWorkspaceFile(
  projectId: string,
  workspaceId: string,
  payload: { path: string; content: string }
): Promise<WorkspaceFile> {
  return apiFetch<WorkspaceFile>(`/api/projects/${projectId}/workspaces/${workspaceId}/files`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createConversationMessage(
  conversationId: string,
  payload: {
    role: MessageRole;
    content: string;
    agent_name?: string | null;
    metadata_json?: Record<string, unknown>;
  }
): Promise<CreateMessageResponse> {
  return apiFetch<CreateMessageResponse>(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateConversationTitle(conversationId: string, title: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function archiveConversation(conversationId: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/conversations/${conversationId}`, {
    method: "DELETE",
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
