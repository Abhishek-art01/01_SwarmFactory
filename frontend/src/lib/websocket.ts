/**
 * websocket.ts
 *
 * Manages a single WebSocket connection per job.
 * Implements:
 *  - Automatic reconnection with exponential back-off (max 5 retries)
 *  - A typed event subscriber pattern so any component can listen
 *  - Clean teardown when the job is done or the component unmounts
 *
 * WebSocket endpoint: ws://localhost:8000/ws/:job_id
 * (Override host via VITE_WS_BASE_URL env var)
 *
 * Usage:
 *   const mgr = createSwarmSocket(jobId);
 *   mgr.on("agent_update", (evt) => { ... });
 *   // later:
 *   mgr.close();
 */

// ─── Config ───────────────────────────────────────────────────────────────────

const WS_BASE: string =
  (import.meta.env.VITE_WS_BASE_URL as string | undefined) ??
  `ws://${window.location.hostname}:8000`;

const MAX_RETRIES = 5;
const BASE_BACKOFF_MS = 1000; // doubles each retry

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
    set?.forEach((fn) => fn(event));
  }

  // What does this do? Opens (or reopens) the WebSocket connection.
  function connect() {
    const url = `${WS_BASE}/ws/${jobId}`;
    ws = new WebSocket(url);
    emitState("connecting");

    // What message type is this handling? Connection opened — reset retry counter.
    ws.onopen = () => {
      console.log("WS state:", ws?.readyState, "— connected to", url);
      retryCount = 0;
      emitState("open");
    };

    // What message type is this handling? Incoming text frame — parse and dispatch to listeners.
    ws.onmessage = (messageEvent: MessageEvent) => {
      let parsed: SwarmEvent;
      try {
        parsed = JSON.parse(messageEvent.data as string) as SwarmEvent;
      } catch (parseErr) {
        console.error("WS parse error:", parseErr, "raw:", messageEvent.data);
        return;
      }

      // Route to the correct typed listener set
      switch (parsed.type) {
        case "agent_update":
          dispatch("agent_update", parsed);
          break;
        case "file_written":
          dispatch("file_written", parsed);
          break;
        case "log":
          dispatch("log", parsed);
          break;
        case "complete":
          dispatch("complete", parsed);
          break;
        case "error":
          dispatch("error", parsed);
          break;
        default: {
          // What message type is this handling? Unknown event — log and ignore.
          const unhandled = parsed as { type: string };
          console.warn("WS: unhandled event type:", unhandled.type);
        }
      }
    };

    // What message type is this handling? Connection closed — schedule reconnect if appropriate.
    ws.onclose = (evt: CloseEvent) => {
      console.log("WS state:", ws?.readyState, "— closed. code:", evt.code);
      emitState("closed");

      if (isManuallyClosed) return;
      if (retryCount >= MAX_RETRIES) {
        console.error("WS: max retries reached, giving up.");
        emitState("error");
        return;
      }

      const delay = BASE_BACKOFF_MS * Math.pow(2, retryCount);
      retryCount++;
      console.log(`WS: reconnecting in ${delay}ms (attempt ${retryCount}/${MAX_RETRIES})`);
      retryTimer = setTimeout(connect, delay);
    };

    // What message type is this handling? WebSocket protocol error.
    ws.onerror = (evt: Event) => {
      console.error("API error: WebSocket error event →", evt);
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
        ws.close(1000, "component unmount");
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
