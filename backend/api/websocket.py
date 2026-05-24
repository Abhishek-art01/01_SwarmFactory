"""
api/websocket.py
----------------
WS /ws/:job_id — Bidirectional streaming of agent events to the frontend.

HOW BIDIRECTIONAL WEBSOCKET STREAMING WORKS HERE:
──────────────────────────────────────────────────
1. The client opens a WebSocket connection to /ws/{job_id}.
2. The server immediately starts polling Redis Pub/Sub channel "job:{job_id}:events".
3. Whenever the Celery worker (running the swarm) publishes an event to that
   channel, this handler receives it and forwards it to the WebSocket client.
4. The client can also SEND messages (e.g. "cancel") which we receive and act on.
5. When the job completes or fails, a final event is emitted and the connection
   is closed gracefully.

Why Redis Pub/Sub and not direct asyncio queues?
  - The Celery worker runs in a DIFFERENT process (possibly on a different machine).
  - asyncio queues only work within the same process.
  - Redis Pub/Sub is the standard cross-process message bus for this pattern.

Event shapes the client will receive:
  { "type": "agent_update", "agent": "coder",   "status": "running", "output": "..." }
  { "type": "file_written", "filename": "main.py" }
  { "type": "complete",     "github_url": "...",  "azure_url": "...", "coverage": 92 }
  { "type": "error",        "message": "..." }
"""

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

# Included in server.py with no prefix, so the full path is WS /ws/{job_id}
router = APIRouter(tags=["WebSocket"])

# How long (seconds) to wait between Redis subscription checks before
# sending a keepalive ping to the client.
KEEPALIVE_INTERVAL = 15.0

# How long (seconds) to wait for the job to appear in Redis before giving up.
JOB_WAIT_TIMEOUT = 30.0


# ── Event helpers ─────────────────────────────────────────────────────────────

def _build_event(event_type: str, **kwargs: Any) -> str:
    """
    Serialise an event dict to a JSON string ready to send over the WebSocket.

    Args:
        event_type: The 'type' field of the event (e.g. 'agent_update').
        **kwargs:   Additional fields merged into the event dict.

    Returns:
        str: JSON-encoded event string.
    """
    payload = {"type": event_type, **kwargs}
    return json.dumps(payload)


async def _safe_send(ws: WebSocket, message: str) -> bool:
    """
    Send a text message over the WebSocket, catching any connection errors.

    Returns False if the connection is already closed (so the caller can stop).

    Args:
        ws:      The active WebSocket connection.
        message: JSON string to send.

    Returns:
        bool: True if send succeeded, False if the connection is gone.
    """
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            # await: we're waiting for the OS to flush the TCP send buffer
            await ws.send_text(message)
            return True
        return False
    except Exception as exc:
        logger.warning("WebSocket send failed", extra={"error": str(exc)})
        return False


# ── WebSocket handler ─────────────────────────────────────────────────────────

# HOW BIDIRECTIONAL STREAMING WORKS HERE:
# We run two concurrent asyncio tasks inside this handler:
#   Task A (listen_to_redis): subscribes to Redis Pub/Sub and forwards
#                             messages to the WebSocket client.
#   Task B (listen_to_client): reads messages from the client (e.g. "cancel").
# Both tasks run concurrently via asyncio.gather(). When either completes
# (job done, client disconnected, error), we cancel the other.
@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str) -> None:
    """
    Stream real-time agent events for a specific job over WebSocket.

    Opens a Redis Pub/Sub subscription on channel 'job:{job_id}:events'
    and forwards every published event to the connected WebSocket client.
    Also listens for inbound messages from the client (e.g. cancellation).

    Args:
        websocket: The WebSocket connection (injected by FastAPI/Starlette).
        job_id:    UUID4 of the job to stream events for.
    """
    # await: WebSocket handshake — TCP upgrade from HTTP to WS protocol
    await websocket.accept()
    logger.info("WebSocket connected", extra={"job_id": job_id})

    # We need a SEPARATE Redis client for Pub/Sub because subscribing puts
    # the connection into a special mode where you can only issue subscribe/
    # unsubscribe/psubscribe commands — you can't interleave regular GET/SET.
    redis_client: aioredis.Redis | None = None
    pubsub = None

    try:
        # ── Verify job exists ─────────────────────────────────────────────────
        app_redis: aioredis.Redis = websocket.app.state.redis

        # await: checking Redis to ensure job_id is valid before we accept streaming
        job_exists = await app_redis.exists(f"job:{job_id}")
        if not job_exists:
            await _safe_send(
                websocket,
                _build_event("error", message=f"Job '{job_id}' not found"),
            )
            await websocket.close(code=1008)  # Policy violation
            return

        # ── Open a dedicated Redis connection for Pub/Sub ─────────────────────
        # await: creating a new TCP connection to Redis for the pub/sub channel
        redis_client = aioredis.from_url(
            websocket.app.state.redis.connection_pool.connection_kwargs.get(
                "connection_class", None
            ) and str(websocket.app.state.redis),
            encoding="utf-8",
            decode_responses=True,
        )
        # Simpler: re-read the URL from settings
        from core.config import settings as _settings
        redis_client = aioredis.from_url(
            _settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )

        pubsub = redis_client.pubsub()
        channel = f"job:{job_id}:events"

        # await: sending the SUBSCRIBE command to Redis
        await pubsub.subscribe(channel)
        logger.info("Redis Pub/Sub subscribed", extra={"job_id": job_id, "channel": channel})

        # Send an initial "connected" acknowledgment so the client knows
        # the stream is live and it doesn't need to wait silently.
        await _safe_send(
            websocket,
            _build_event("connected", job_id=job_id, message="Stream connected"),
        )

        # ── Concurrent task: forward Redis events → WebSocket ────────────────
        async def listen_to_redis() -> None:
            """
            Receive messages from Redis Pub/Sub and forward to the WebSocket client.

            Runs until the job emits a terminal event ('complete' or 'error')
            or until cancelled by the outer gather().
            """
            keepalive_counter = 0.0

            while True:
                try:
                    # await: non-blocking get from the Redis Pub/Sub queue.
                    # timeout=1.0 means we check every second; this lets us
                    # send keepalive pings even when no events are flowing.
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                except Exception as exc:
                    logger.error(
                        "Redis Pub/Sub read error",
                        extra={"job_id": job_id, "error": str(exc)},
                    )
                    break

                if message and message.get("type") == "message":
                    raw_data: str = message["data"]
                    logger.debug(
                        "Event received from Redis",
                        extra={"job_id": job_id, "data": raw_data[:120]},
                    )

                    # Forward the event verbatim to the WebSocket client
                    sent = await _safe_send(websocket, raw_data)
                    if not sent:
                        break  # Client disconnected

                    # Check if this is a terminal event — if so, we're done
                    try:
                        parsed = json.loads(raw_data)
                        if parsed.get("type") in ("complete", "error"):
                            logger.info(
                                "Terminal event received, closing stream",
                                extra={"job_id": job_id, "event_type": parsed.get("type")},
                            )
                            return  # Exit cleanly — this task is done
                    except json.JSONDecodeError:
                        pass  # Non-JSON message; ignore and continue

                else:
                    # No message this tick — send a keepalive ping periodically
                    keepalive_counter += 1.0
                    if keepalive_counter >= KEEPALIVE_INTERVAL:
                        keepalive_counter = 0.0
                        sent = await _safe_send(
                            websocket, _build_event("ping", job_id=job_id)
                        )
                        if not sent:
                            break

        # ── Concurrent task: receive messages from the WebSocket client ───────
        async def listen_to_client() -> None:
            """
            Handle inbound messages from the WebSocket client.

            Currently supports:
              { "type": "cancel" } — marks the job as cancelled in Redis.
              { "type": "ping"   } — echoes a pong (connection check).

            Runs until the client disconnects or sends a 'close' message.
            """
            while True:
                try:
                    # await: blocking read — waiting for the client to send us a message.
                    # This yields control to the event loop so listen_to_redis() can run.
                    raw = await websocket.receive_text()
                except WebSocketDisconnect:
                    logger.info(
                        "WebSocket client disconnected",
                        extra={"job_id": job_id},
                    )
                    return
                except Exception as exc:
                    logger.warning(
                        "WebSocket receive error",
                        extra={"job_id": job_id, "error": str(exc)},
                    )
                    return

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue  # Ignore non-JSON

                msg_type = msg.get("type")
                logger.info(
                    "Client message received",
                    extra={"job_id": job_id, "msg_type": msg_type},
                )

                if msg_type == "cancel":
                    # Mark the job as cancelled in Redis so the Celery worker
                    # will stop processing on its next checkpoint.
                    try:
                        # await: writing cancellation flag to Redis
                        await app_redis.hset(
                            f"job:{job_id}", mapping={"status": "cancelled"}
                        )
                        await _safe_send(
                            websocket,
                            _build_event("cancelled", job_id=job_id, message="Job cancelled"),
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to cancel job",
                            extra={"job_id": job_id, "error": str(exc)},
                        )
                    return  # Close the WS after cancellation

                elif msg_type == "ping":
                    await _safe_send(websocket, _build_event("pong", job_id=job_id))

        # ── Run both tasks concurrently ───────────────────────────────────────
        # asyncio.gather runs both coroutines on the same event loop thread.
        # When ONE finishes (job complete, client disconnects), we cancel the other.
        # return_exceptions=True prevents one task's exception from silently
        # swallowing the other task's result.
        await asyncio.gather(
            listen_to_redis(),
            listen_to_client(),
            return_exceptions=True,
        )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during setup", extra={"job_id": job_id})

    except Exception as exc:
        logger.error(
            "WebSocket handler error",
            extra={"job_id": job_id, "error": str(exc)},
        )
        await _safe_send(
            websocket,
            _build_event("error", message="Internal server error in WebSocket handler"),
        )

    finally:
        # ── Cleanup ───────────────────────────────────────────────────────────
        if pubsub:
            try:
                # await: sending UNSUBSCRIBE to Redis to clean up the subscription
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:
                pass  # Best-effort cleanup

        if redis_client:
            try:
                # await: closing the dedicated Redis connection for Pub/Sub
                await redis_client.aclose()
            except Exception:
                pass

        # Close the WebSocket if it's still open
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass

        logger.info("WebSocket handler exited", extra={"job_id": job_id})
