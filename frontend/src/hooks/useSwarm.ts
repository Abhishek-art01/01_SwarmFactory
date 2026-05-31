/**
 * useSwarm
 *
 * The primary orchestration hook for a live swarm job.
 * Connects a WebSocket for real-time updates, falls back to HTTP polling
 * every 3 s if the WS drops, and exposes all the state a dashboard needs.
 *
 * Usage:
 *   const { agents, stage, logs, files, wsState } = useSwarm(jobId);
 *
 * Pass `null` as jobId to stay idle.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { createSwarmSocket, WsConnectionState } from "../lib/websocket";
import { ApiError, getJobStatus, Agent, JobStatus } from "../lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface LogLine {
  id: string;
  timestamp: string;
  agent?: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface WrittenFile {
  path: string;
  language: string;
  size: number;
  agent: string;
  writtenAt: string;
}

export interface SwarmState {
  agents: Agent[];
  stage: string;
  stageIndex: number;
  overallProgress: number;
  logs: LogLine[];
  files: WrittenFile[];
  wsState: WsConnectionState;
  isComplete: boolean;
  error: string | null;
}

const POLL_INTERVAL_MS = 3000;
const MAX_LOG_LINES = 500;

// ─── Helper ───────────────────────────────────────────────────────────────────

/** What does this do? Generates a unique id for each log line. */
let _logCounter = 0;
function nextLogId() {
  return `log-${Date.now()}-${++_logCounter}`;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useSwarm(jobId: string | null): SwarmState {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [stage, setStage] = useState("");
  const [stageIndex, setStageIndex] = useState(0);
  const [overallProgress, setOverallProgress] = useState(0);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [files, setFiles] = useState<WrittenFile[]>([]);
  const [wsState, setWsState] = useState<WsConnectionState>("closed");
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shouldPoll, setShouldPoll] = useState(true);

  // Ref so polling can check if WS is alive before making HTTP calls
  const wsStateRef = useRef<WsConnectionState>("closed");

  // What does this do? Appends a new log line, capping the buffer at MAX_LOG_LINES.
  const appendLog = useCallback((line: Omit<LogLine, "id">) => {
    setLogs((prev) => {
      const next = [...prev, { ...line, id: nextLogId() }];
      return next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next;
    });
  }, []);

  // What does this do? Applies a status/progress update to a single agent by id.
  const patchAgent = useCallback(
    (agentId: string, patch: Partial<Agent>) => {
      setAgents((prev) => {
        const current = Array.isArray(prev) ? prev : [];
        const existing = current.find((a) => a.id === agentId);
        if (!existing) {
          return [
            ...current,
            {
              id: agentId,
              name: agentId,
              role: "Swarm agent",
              status: "idle",
              progress: 0,
              updatedAt: new Date().toISOString(),
              ...patch,
            },
          ];
        }
        return current.map((a) => (a.id === agentId ? { ...a, ...patch } : a));
      });
    },
    []
  );

  // ─── WebSocket setup ────────────────────────────────────────────────────────

  // When does this run and why?
  // Runs whenever jobId changes. Opens a WS connection for the new job and
  // tears down the old one when jobId changes or the component unmounts.
  useEffect(() => {
    if (!jobId) return;

    setIsComplete(false);
    setError(null);
    setShouldPoll(true);

    const socket = createSwarmSocket(jobId);

    // Track WS state for the polling fallback
    const unsubState = socket.onStateChange((s) => {
      setWsState(s);
      wsStateRef.current = s;
    });

    // What message type is this handling? agent_update — update a single agent's status.
    const unsubAgent = socket.on("agent_update", (evt) => {
      patchAgent(evt.agent, {
        status: evt.data.status,
        progress: evt.data.progress,
        currentTask: evt.data.currentTask,
        updatedAt: new Date().toISOString(),
      });
    });

    // What message type is this handling? file_written — add a new file to the tree.
    const unsubFile = socket.on("file_written", (evt) => {
      setFiles((prev) => {
        // De-duplicate: if the same path is written again, replace it
        const filtered = prev.filter((f) => f.path !== evt.data.path);
        return [
          ...filtered,
          {
            path: evt.data.path,
            language: evt.data.language,
            size: evt.data.size,
            agent: evt.agent,
            writtenAt: new Date().toISOString(),
          },
        ];
      });
    });

    // What message type is this handling? log — append text to the live log feed.
    const unsubLog = socket.on("log", (evt) => {
      appendLog({
        timestamp: evt.data.timestamp,
        agent: evt.agent,
        level: evt.data.level,
        message: evt.data.message,
      });
    });

    // What message type is this handling? complete — mark the job done.
    const unsubComplete = socket.on("complete", () => {
      setIsComplete(true);
      setOverallProgress(100);
      appendLog({
        timestamp: new Date().toISOString(),
        level: "info",
        message: "✓ Swarm job complete.",
      });
    });

    // What message type is this handling? error — surface a fatal job error.
    const unsubError = socket.on("error", (evt) => {
      setError(evt.data.message);
      appendLog({
        timestamp: new Date().toISOString(),
        level: "error",
        message: `Fatal error: ${evt.data.message}`,
      });
    });

    return () => {
      unsubState();
      unsubAgent();
      unsubFile();
      unsubLog();
      unsubComplete();
      unsubError();
      socket.close();
    };
  }, [jobId, appendLog, patchAgent]);

  // ─── HTTP polling fallback ──────────────────────────────────────────────────

  // When does this run and why?
  // Polls /api/status every 3 s. Skips the call if the WS is healthy ("open")
  // to avoid double-updating state from both channels simultaneously.
  useEffect(() => {
    if (!jobId || isComplete || !shouldPoll) return;

    const tick = async () => {
      // Don't poll while the WS is delivering updates
      if (wsStateRef.current === "open") return;

      try {
        const status: JobStatus = await getJobStatus(jobId);
        setStage(status.stage);
        setStageIndex(status.stageIndex);
        setOverallProgress(status.overallProgress);
        setAgents(Array.isArray(status.agents) ? status.agents : []);
        if (status.error) setError(status.error);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setShouldPoll(false);
          setError(`Job '${jobId}' was not found.`);
          return;
        }
        console.error("API error: polling /api/status →", err);
      }
    };

    const id = setInterval(tick, POLL_INTERVAL_MS);
    // Run immediately on mount so we don't wait 3 s for the first snapshot
    void tick();

    return () => clearInterval(id);
  }, [jobId, isComplete, shouldPoll]);

  return {
    agents,
    stage,
    stageIndex,
    overallProgress,
    logs,
    files,
    wsState,
    isComplete,
    error,
  };
}
