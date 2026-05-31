/**
 * websocket.ts
 *
 * Manages a single WebSocket connection per job.
 * Implements:
 *  - Automatic reconnection with exponential back-off (max 5 retries)
 *  - A typed event subscriber pattern so any component can listen
 *  - Clean teardown when the job is done or the component unmounts
 *
 * WebSocket endpoint defaults to the current origin's /ws/:job_id path.
 * In Vite dev, /ws is proxied to the FastAPI backend by vite.config.ts.
 * Override with VITE_WS_BASE_URL or VITE_WS_URL when the backend is on another origin.
 *
 * Usage:
 *   const mgr = createSwarmSocket(jobId);
 *   mgr.on("agent_update", (evt) => { ... });
 *   // later:
 *   mgr.close();
 */

// ─── Config ───────────────────────────────────────────────────────────────────

const WS_BASE: string =
  (import.meta.env.VITE_WS_BASE_URL as string | undefined) ||
  (import.meta.env.VITE_WS_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;

const MAX_RETRIES = 5;
const BASE_BACKOFF_MS = 1000; // doubles each retry
const NORMAL_CLOSE = 1000;

// ─── Typed event shapes ───────────────────────────────────────────────────────

/** Emitted when any agent changes state or progress */
export interface AgentUpdateEvent {
  type: "agent_update";
  agent: string;
  data: {
    status: "idle" | "running" | "done" | "error";
    progress: number;
    currentTask?: string;
  };
}

/** Emitted each time an agent writes a new file to disk */
export interface FileWrittenEvent {
  type: "file_written";
  agent: string;
  data: {
    path: string;
    language: string;
    size: number;
  };
}

/** Plain text log line from any agent */
export interface LogEvent {
  type: "log";
  agent?: string;
  data: {
    level: "info" | "warn" | "error";
    message: string;
    timestamp: string;
  };
}

/** The job has completed (all agents done) */
export interface CompleteEvent {
  type: "complete";
  data: {
    jobId: string;
  };
}

/** The job encountered a fatal error */
export interface ErrorEvent {
  type: "error";
  data: {
    message: string;
    code?: string;
  };
}

export type SwarmEvent =
  | AgentUpdateEvent
  | FileWrittenEvent
  | LogEvent
  | CompleteEvent
  | ErrorEvent;

export type SwarmEventType = SwarmEvent["type"];

// ─── Listener registry ────────────────────────────────────────────────────────

type Listener<T extends SwarmEvent> = (event: T) => void;
type ListenerMap = {
  [K in SwarmEventType]?: Set<Listener<Extract<SwarmEvent, { type: K }>>>;
};

// ─── Connection state ─────────────────────────────────────────────────────────

export type WsConnectionState = "connecting" | "open" | "closing" | "closed" | "error";

export interface SwarmSocket {
  /** Register a typed event listener */
  on: <K extends SwarmEventType>(
    type: K,
    listener: Listener<Extract<SwarmEvent, { type: K }>>
  ) => () => void;
  /** Remove all listeners and close the socket */
  close: () => void;
  /** Subscribe to connection state changes */
  onStateChange: (cb: (state: WsConnectionState) => void) => () => void;
}

type RawWsEvent = {
  type?: unknown;
  agent?: unknown;
  data?: unknown;
  status?: unknown;
  progress?: unknown;
  currentTask?: unknown;
  output?: unknown;
  filename?: unknown;
  path?: unknown;
  language?: unknown;
  size?: unknown;
  timestamp?: unknown;
  level?: unknown;
  message?: unknown;
  code?: unknown;
  job_id?: unknown;
  jobId?: unknown;
};

function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function normalizeStatus(value: unknown): AgentUpdateEvent["data"]["status"] {
  if (value === "complete") return "done";
  if (value === "idle" || value === "running" || value === "done" || value === "error") return value;
  return "running";
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
    default:
      return extension || "text";
  }
}

function normalizeEvent(raw: RawWsEvent): SwarmEvent | null {
  const data = asObject(raw.data);
  const type = asString(raw.type);

  switch (type) {
    case "agent_update": {
      const message = asString(data.message, asString(raw.output));
      return {
        type,
        agent: asString(raw.agent, "swarm"),
        data: {
          status: normalizeStatus(data.status ?? raw.status),
          progress: asNumber(data.progress ?? raw.progress),
          currentTask: asString(data.currentTask ?? raw.currentTask, message),
        },
      };
    }

    case "file_written": {
      const path = asString(data.path, asString(raw.path, asString(raw.filename)));
      return {
        type,
        agent: asString(raw.agent, "swarm"),
        data: {
          path,
          language: asString(data.language ?? raw.language, inferLanguage(path)),
          size: asNumber(data.size ?? raw.size),
        },
      };
    }

    case "log":
      return {
        type,
        agent: typeof raw.agent === "string" ? raw.agent : undefined,
        data: {
          level:
            data.level === "warn" || data.level === "error" || data.level === "info"
              ? data.level
              : "info",
          message: asString(data.message ?? raw.message ?? raw.output),
          timestamp: asString(data.timestamp ?? raw.timestamp, new Date().toISOString()),
        },
      };

    case "complete":
      return {
        type,
        data: {
          jobId: asString(data.jobId ?? data.job_id ?? raw.jobId ?? raw.job_id),
        },
      };

    case "error":
      return {
        type,
        data: {
          message: asString(data.message ?? raw.message, "WebSocket stream error"),
          code: typeof data.code === "string" ? data.code : typeof raw.code === "string" ? raw.code : undefined,
        },
      };

    default:
      return null;
  }
}

// ─── Factory function ─────────────────────────────────────────────────────────

/**
 * What does this do?
 * Creates a managed WebSocket for the given jobId.
 * Returns a handle with .on() for listening to events and .close() to tear down.
 */
export function createSwarmSocket(jobId: string): SwarmSocket {
  const listeners: ListenerMap = {};
  const stateListeners = new Set<(state: WsConnectionState) => void>();

  let ws: WebSocket | null = null;
  let retryCount = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let isManuallyClosed = false;

  // What does this do? Notifies all state subscribers of a new connection state.
  function emitState(state: WsConnectionState) {
    stateListeners.forEach((cb) => cb(state));
  }

  // What does this do? Dispatches a parsed SwarmEvent to the correct listener set.
  function dispatch<K extends SwarmEventType>(
    type: K,
    event: Extract<SwarmEvent, { type: K }>
  ) {
    const set = listeners[type] as Set<Listener<Extract<SwarmEvent, { type: K }>>> | undefined;
    set?.forEach((fn) => {
      try {
        fn(event);
      } catch (listenerErr) {
        console.error("WS listener error:", listenerErr);
      }
    });
  }

  // What does this do? Opens (or reopens) the WebSocket connection.
  function connect() {
    const params = API_KEY ? `?api_key=${encodeURIComponent(API_KEY)}` : "";
    const url = `${WS_BASE}/ws/${encodeURIComponent(jobId)}${params}`;
    const socket = new WebSocket(url);
    ws = socket;
    emitState("connecting");

    // What message type is this handling? Connection opened — reset retry counter.
    socket.onopen = () => {
      if (socket !== ws) return;
      retryCount = 0;
      emitState("open");
    };

    // What message type is this handling? Incoming text frame — parse and dispatch to listeners.
    socket.onmessage = (messageEvent: MessageEvent) => {
      if (socket !== ws) return;

      let parsed: unknown;
      try {
        parsed = JSON.parse(messageEvent.data as string) as unknown;
      } catch (parseErr) {
        console.error("WS parse error:", parseErr, "raw:", messageEvent.data);
        return;
      }

      const normalized = normalizeEvent(parsed as RawWsEvent);
      if (!normalized) {
        const raw = parsed as RawWsEvent;
        if (raw.type !== "connected" && raw.type !== "ping" && raw.type !== "pong" && raw.type !== "cancelled") {
          console.warn("WS: unhandled event type:", raw.type);
        }
        return;
      }

      // Route to the correct typed listener set
      switch (normalized.type) {
        case "agent_update":
          dispatch("agent_update", normalized);
          break;
        case "file_written":
          dispatch("file_written", normalized);
          break;
        case "log":
          dispatch("log", normalized);
          break;
        case "complete":
          dispatch("complete", normalized);
          break;
        case "error":
          dispatch("error", normalized);
          break;
      }
    };

    // What message type is this handling? Connection closed — schedule reconnect if appropriate.
    socket.onclose = (evt: CloseEvent) => {
      if (socket !== ws && !isManuallyClosed) return;
      emitState("closed");

      if (isManuallyClosed) return;
      if (evt.code === NORMAL_CLOSE) return;
      if (retryCount >= MAX_RETRIES) {
        emitState("error");
        return;
      }

      const delay = BASE_BACKOFF_MS * Math.pow(2, retryCount);
      retryCount++;
      retryTimer = setTimeout(connect, delay);
    };

    // What message type is this handling? WebSocket protocol error.
    socket.onerror = () => {
      if (socket !== ws) return;
      emitState("error");
      // onclose fires after onerror, which will handle reconnect
    };
  }

  // Bootstrap the connection
  connect();

  // ─── Public API ─────────────────────────────────────────────────────────────

  return {
    // What does this do? Registers a typed listener; returns an unsubscribe function.
    on<K extends SwarmEventType>(
      type: K,
      listener: Listener<Extract<SwarmEvent, { type: K }>>
    ): () => void {
      if (!listeners[type]) {
        listeners[type] = new Set() as ListenerMap[K];
      }
      (listeners[type] as Set<Listener<Extract<SwarmEvent, { type: K }>>>).add(listener);
      return () => {
        (listeners[type] as Set<Listener<Extract<SwarmEvent, { type: K }>>>).delete(listener);
      };
    },

    // What does this do? Cleans up timers, closes the socket, empties listener maps.
    close() {
      isManuallyClosed = true;
      if (retryTimer !== null) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      if (ws) {
        emitState("closing");
        ws.close(NORMAL_CLOSE, "component unmount");
        ws = null;
      }
      // Clear all listeners
      (Object.keys(listeners) as SwarmEventType[]).forEach((k) => {
        delete listeners[k];
      });
      stateListeners.clear();
    },

    // What does this do? Lets external code react to WS connection lifecycle changes.
    onStateChange(cb: (state: WsConnectionState) => void): () => void {
      stateListeners.add(cb);
      return () => stateListeners.delete(cb);
    },
  };
}
