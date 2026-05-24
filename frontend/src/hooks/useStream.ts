/**
 * useStream
 *
 * A lightweight hook for components that only care about a raw stream
 * of SwarmEvents from the WebSocket — without the full agent/file state
 * management that useSwarm provides.
 *
 * Useful for: LiveLog.tsx (which just needs log events) or any component
 * that wants to subscribe to a single event type from an existing job.
 *
 * Usage:
 *   const { events, wsState } = useStream<LogEvent>(jobId, "log");
 */

import { useState, useEffect } from "react";
import { createSwarmSocket, SwarmEvent, SwarmEventType, WsConnectionState } from "../lib/websocket";

// ─── Hook ─────────────────────────────────────────────────────────────────────

interface UseStreamResult<T extends SwarmEvent> {
  /** All events received since the hook mounted */
  events: T[];
  /** Current WebSocket connection state */
  wsState: WsConnectionState;
  /** Clear the accumulated event buffer */
  clearEvents: () => void;
}

/**
 * What does this do?
 * Opens (or shares) a WebSocket for the given jobId and collects all events
 * of the specified type. Returns a growing array of typed events.
 *
 * @param jobId   The job whose stream to subscribe to (pass null to stay idle)
 * @param type    The SwarmEvent type to filter for
 * @param maxItems  Maximum number of events to retain in the buffer (default 200)
 */
export function useStream<K extends SwarmEventType>(
  jobId: string | null,
  type: K,
  maxItems = 200
): UseStreamResult<Extract<SwarmEvent, { type: K }>> {
  type FilteredEvent = Extract<SwarmEvent, { type: K }>;

  const [events, setEvents] = useState<FilteredEvent[]>([]);
  const [wsState, setWsState] = useState<WsConnectionState>("closed");

  // When does this run and why?
  // Opens a fresh WebSocket subscription whenever jobId or event type changes.
  // Tears everything down on unmount or when deps change.
  useEffect(() => {
    if (!jobId) {
      setEvents([]);
      setWsState("closed");
      return;
    }

    const socket = createSwarmSocket(jobId);

    const unsubState = socket.onStateChange(setWsState);

    // What message type is this handling? The caller-specified event type.
    const unsubEvents = socket.on(type, (evt) => {
      setEvents((prev) => {
        const next = [...prev, evt as FilteredEvent];
        return next.length > maxItems ? next.slice(-maxItems) : next;
      });
    });

    return () => {
      unsubState();
      unsubEvents();
      socket.close();
    };
  }, [jobId, type, maxItems]);

  // What does this do? Lets the parent component clear the event buffer (e.g., on replay).
  const clearEvents = () => setEvents([]);

  return { events, wsState, clearEvents };
}
