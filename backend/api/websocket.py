"""
api/websocket.py
----------------
WS /ws/:job_id - Bidirectional streaming of agent events to the frontend.
"""

import asyncio
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from starlette.websockets import WebSocketState

from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])

KEEPALIVE_INTERVAL = 15.0
REDIS_READ_TIMEOUT = 1.0
JOB_WAIT_TIMEOUT = 30.0
WS_POLICY_VIOLATION = 1008
WS_INTERNAL_ERROR = 1011


class ClientMessage(BaseModel):
    """Validated inbound WebSocket command."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cancel", "ping", "close"]

    @field_validator("type", mode="before")
    @classmethod
    def type_must_be_present(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("type is required")
        return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_message(message: Any, limit: int = 1000) -> str | None:
    if message is None:
        return None
    text = message if isinstance(message, str) else repr(message)
    return text if len(text) <= limit else f"{text[:limit]}...<truncated>"


def _error_payload(error_type: str, message: str, **kwargs: Any) -> str:
    payload = {"type": "error", "error_type": error_type, "message": message, **kwargs}
    return json.dumps(payload)


def _build_event(event_type: str, **kwargs: Any) -> str:
    payload = {"type": event_type, **kwargs}
    return json.dumps(payload)


def _ws_log(
    level: int,
    event: str,
    *,
    connection_id: str,
    job_id: str,
    user_id: str | None = None,
    incoming_message: Any = None,
    exc: BaseException | None = None,
    **fields: Any,
) -> None:
    """Emit one JSON log record with WebSocket context and optional stack trace."""

    payload: dict[str, Any] = {
        "timestamp": _utc_now(),
        "event": event,
        "websocket_connection_id": connection_id,
        "job_id": job_id,
        "user_id": user_id,
        "incoming_message": _short_message(incoming_message),
        **fields,
    }
    if exc is not None:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)
        payload["stack_trace"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )

    logger.log(level, json.dumps(payload, default=str))


async def _safe_send(
    ws: WebSocket,
    message: str,
    *,
    connection_id: str,
    job_id: str,
    user_id: str | None,
) -> bool:
    try:
        if (
            ws.client_state == WebSocketState.CONNECTED
            and ws.application_state == WebSocketState.CONNECTED
        ):
            await ws.send_text(message)
            return True
        return False
    except Exception as exc:
        _ws_log(
            logging.WARNING,
            "websocket_send_failed",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
            incoming_message=message,
            exc=exc,
        )
        return False


async def _close_gracefully(
    ws: WebSocket,
    *,
    code: int,
    reason: str,
    connection_id: str,
    job_id: str,
    user_id: str | None,
) -> None:
    if (
        ws.client_state != WebSocketState.CONNECTED
        or ws.application_state != WebSocketState.CONNECTED
    ):
        return
    try:
        await ws.close(code=code, reason=reason[:123])
    except Exception as exc:
        _ws_log(
            logging.WARNING,
            "websocket_close_failed",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
            exc=exc,
            close_code=code,
            close_reason=reason,
        )


def _validate_job_id(job_id: str) -> str | None:
    try:
        uuid.UUID(job_id, version=4)
    except (TypeError, ValueError):
        return "job_id must be a valid UUID4"
    return None


def _authenticate(websocket: WebSocket) -> tuple[bool, str | None, str | None]:
    token = websocket.query_params.get("api_key") or websocket.query_params.get("token")
    if not token:
        return False, None, "Missing WebSocket API key"
    if token != settings.API_KEY:
        return False, None, "Invalid WebSocket API key"
    return True, "api-key", None


def _parse_client_message(raw: str) -> tuple[ClientMessage | None, str | None]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON payload: {exc.msg}"

    if not isinstance(decoded, dict):
        return None, "WebSocket payload must be a JSON object"

    try:
        return ClientMessage.model_validate(decoded), None
    except ValidationError as exc:
        return None, exc.errors(include_url=False)[0]["msg"]


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str) -> None:
    """
    Stream real-time agent events for a specific job over WebSocket.

    Lifecycle:
      1. Accept connection so failures can be returned as JSON frames.
      2. Authenticate the query-string API key.
      3. Validate job_id and verify the Redis job state exists.
      4. Subscribe to Redis Pub/Sub and forward events to the client.
      5. Validate every inbound client message before business logic.
      6. Close with a meaningful WebSocket close code/reason on failures.
    """

    connection_id = str(uuid.uuid4())
    user_id: str | None = None
    app_redis: aioredis.Redis | None = None
    redis_client: aioredis.Redis | None = None
    pubsub: Any = None

    await websocket.accept()
    _ws_log(
        logging.INFO,
        "websocket_connected",
        connection_id=connection_id,
        job_id=job_id,
        client=str(websocket.client) if websocket.client else None,
    )

    try:
        authenticated, user_id, auth_error = _authenticate(websocket)
        if not authenticated:
            _ws_log(
                logging.WARNING,
                "websocket_auth_failed",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
                reason=auth_error,
            )
            await _safe_send(
                websocket,
                _error_payload("authentication_failed", auth_error or "Authentication failed"),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_POLICY_VIOLATION,
                reason=auth_error or "Authentication failed",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return

        job_id_error = _validate_job_id(job_id)
        if job_id_error:
            _ws_log(
                logging.WARNING,
                "websocket_job_id_invalid",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
                reason=job_id_error,
            )
            await _safe_send(
                websocket,
                _error_payload("invalid_job_id", job_id_error),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_POLICY_VIOLATION,
                reason=job_id_error,
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return

        try:
            app_redis = websocket.app.state.redis
            job_exists = await asyncio.wait_for(
                app_redis.exists(f"job:{job_id}"), timeout=JOB_WAIT_TIMEOUT
            )
        except asyncio.TimeoutError as exc:
            _ws_log(
                logging.ERROR,
                "websocket_job_lookup_timeout",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
                exc=exc,
            )
            await _safe_send(
                websocket,
                _error_payload("timeout", "Timed out while verifying job state"),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_INTERNAL_ERROR,
                reason="Timed out while verifying job state",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return
        except Exception as exc:
            _ws_log(
                logging.ERROR,
                "websocket_job_lookup_failed",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
                exc=exc,
            )
            await _safe_send(
                websocket,
                _error_payload("database_error", "Unable to verify job state"),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_INTERNAL_ERROR,
                reason="Unable to verify job state",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return

        if not job_exists:
            await _safe_send(
                websocket,
                _error_payload("job_not_found", f"Job '{job_id}' not found"),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_POLICY_VIOLATION,
                reason="Job not found",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return

        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=REDIS_READ_TIMEOUT + 5,
        )
        pubsub = redis_client.pubsub()
        channel = f"job:{job_id}:events"

        try:
            await asyncio.wait_for(pubsub.subscribe(channel), timeout=JOB_WAIT_TIMEOUT)
        except asyncio.TimeoutError as exc:
            _ws_log(
                logging.ERROR,
                "websocket_redis_subscribe_timeout",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
                exc=exc,
                channel=channel,
            )
            await _safe_send(
                websocket,
                _error_payload("timeout", "Timed out subscribing to job events"),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_INTERNAL_ERROR,
                reason="Timed out subscribing to job events",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return
        except Exception as exc:
            _ws_log(
                logging.ERROR,
                "websocket_redis_subscribe_failed",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
                exc=exc,
                channel=channel,
            )
            await _safe_send(
                websocket,
                _error_payload("database_error", "Unable to subscribe to job events"),
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            await _close_gracefully(
                websocket,
                code=WS_INTERNAL_ERROR,
                reason="Unable to subscribe to job events",
                connection_id=connection_id,
                job_id=job_id,
                user_id=user_id,
            )
            return

        _ws_log(
            logging.INFO,
            "websocket_redis_subscribed",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
            channel=channel,
        )
        await _safe_send(
            websocket,
            _build_event("connected", job_id=job_id, message="Stream connected"),
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )

        stop_event = asyncio.Event()

        async def listen_to_redis() -> None:
            keepalive_counter = 0.0
            while not stop_event.is_set():
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=REDIS_READ_TIMEOUT,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _ws_log(
                        logging.ERROR,
                        "websocket_redis_read_failed",
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                        exc=exc,
                    )
                    await _safe_send(
                        websocket,
                        _error_payload("database_error", "Lost connection to job event stream"),
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                    )
                    stop_event.set()
                    return

                if message and message.get("type") == "message":
                    raw_data = message.get("data")
                    if raw_data is None:
                        _ws_log(
                            logging.WARNING,
                            "websocket_redis_message_missing_data",
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                            incoming_message=message,
                        )
                        continue

                    if not isinstance(raw_data, str):
                        raw_data = json.dumps(raw_data, default=str)

                    _ws_log(
                        logging.DEBUG,
                        "websocket_redis_message_received",
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                        incoming_message=raw_data,
                    )

                    sent = await _safe_send(
                        websocket,
                        raw_data,
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                    )
                    if not sent:
                        stop_event.set()
                        return

                    try:
                        parsed = json.loads(raw_data)
                    except json.JSONDecodeError as exc:
                        _ws_log(
                            logging.WARNING,
                            "websocket_redis_message_invalid_json",
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                            incoming_message=raw_data,
                            exc=exc,
                        )
                        continue

                    if isinstance(parsed, dict) and parsed.get("type") in ("complete", "error"):
                        _ws_log(
                            logging.INFO,
                            "websocket_terminal_event_received",
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                            incoming_message=raw_data,
                            event_type=parsed.get("type"),
                        )
                        stop_event.set()
                        return
                else:
                    keepalive_counter += REDIS_READ_TIMEOUT
                    if keepalive_counter >= KEEPALIVE_INTERVAL:
                        keepalive_counter = 0.0
                        sent = await _safe_send(
                            websocket,
                            _build_event("ping", job_id=job_id),
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                        )
                        if not sent:
                            stop_event.set()
                            return

        async def listen_to_client() -> None:
            while not stop_event.is_set():
                try:
                    raw = await websocket.receive_text()
                except WebSocketDisconnect as exc:
                    _ws_log(
                        logging.INFO,
                        "websocket_client_disconnected",
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                        close_code=exc.code,
                        close_reason=getattr(exc, "reason", None),
                    )
                    stop_event.set()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _ws_log(
                        logging.WARNING,
                        "websocket_receive_failed",
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                        exc=exc,
                    )
                    stop_event.set()
                    return

                parsed, validation_error = _parse_client_message(raw)
                if validation_error or parsed is None:
                    _ws_log(
                        logging.WARNING,
                        "websocket_client_message_invalid",
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                        incoming_message=raw,
                        validation_error=validation_error,
                    )
                    await _safe_send(
                        websocket,
                        _error_payload(
                            "invalid_message",
                            validation_error or "Invalid WebSocket payload",
                        ),
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                    )
                    await _close_gracefully(
                        websocket,
                        code=WS_POLICY_VIOLATION,
                        reason=validation_error or "Invalid WebSocket payload",
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                    )
                    stop_event.set()
                    return

                _ws_log(
                    logging.INFO,
                    "websocket_client_message_received",
                    connection_id=connection_id,
                    job_id=job_id,
                    user_id=user_id,
                    incoming_message=raw,
                    msg_type=parsed.type,
                )

                if parsed.type == "cancel":
                    try:
                        await asyncio.wait_for(
                            app_redis.hset(f"job:{job_id}", mapping={"status": "cancelled"}),
                            timeout=JOB_WAIT_TIMEOUT,
                        )
                    except asyncio.TimeoutError as exc:
                        _ws_log(
                            logging.ERROR,
                            "websocket_cancel_timeout",
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                            incoming_message=raw,
                            exc=exc,
                        )
                        await _safe_send(
                            websocket,
                            _error_payload("timeout", "Timed out cancelling job"),
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                        )
                        stop_event.set()
                        return
                    except Exception as exc:
                        _ws_log(
                            logging.ERROR,
                            "websocket_cancel_failed",
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                            incoming_message=raw,
                            exc=exc,
                        )
                        await _safe_send(
                            websocket,
                            _error_payload("database_error", "Unable to cancel job"),
                            connection_id=connection_id,
                            job_id=job_id,
                            user_id=user_id,
                        )
                        stop_event.set()
                        return

                    await _safe_send(
                        websocket,
                        _build_event("cancelled", job_id=job_id, message="Job cancelled"),
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                    )
                    stop_event.set()
                    return

                if parsed.type == "ping":
                    await _safe_send(
                        websocket,
                        _build_event("pong", job_id=job_id),
                        connection_id=connection_id,
                        job_id=job_id,
                        user_id=user_id,
                    )
                    continue

                if parsed.type == "close":
                    stop_event.set()
                    return

        tasks = [
            asyncio.create_task(listen_to_redis(), name=f"ws:{connection_id}:redis"),
            asyncio.create_task(listen_to_client(), name=f"ws:{connection_id}:client"),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        stop_event.set()

        for task in done:
            try:
                task.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _ws_log(
                    logging.ERROR,
                    "websocket_task_crashed",
                    connection_id=connection_id,
                    job_id=job_id,
                    user_id=user_id,
                    exc=exc,
                    task_name=task.get_name(),
                )
                await _safe_send(
                    websocket,
                    _error_payload("internal_error", "WebSocket stream task failed"),
                    connection_id=connection_id,
                    job_id=job_id,
                    user_id=user_id,
                )

        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    except WebSocketDisconnect as exc:
        _ws_log(
            logging.INFO,
            "websocket_disconnected",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
            close_code=exc.code,
            close_reason=getattr(exc, "reason", None),
        )
    except Exception as exc:
        _ws_log(
            logging.ERROR,
            "websocket_handler_unhandled_exception",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
            exc=exc,
        )
        await _safe_send(
            websocket,
            _error_payload("internal_error", "Internal server error in WebSocket handler"),
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )
        await _close_gracefully(
            websocket,
            code=WS_INTERNAL_ERROR,
            reason="Internal server error in WebSocket handler",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )
    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception as exc:
                _ws_log(
                    logging.WARNING,
                    "websocket_pubsub_cleanup_failed",
                    connection_id=connection_id,
                    job_id=job_id,
                    user_id=user_id,
                    exc=exc,
                )

        if redis_client:
            try:
                await redis_client.aclose()
            except Exception as exc:
                _ws_log(
                    logging.WARNING,
                    "websocket_redis_cleanup_failed",
                    connection_id=connection_id,
                    job_id=job_id,
                    user_id=user_id,
                    exc=exc,
                )

        await _close_gracefully(
            websocket,
            code=1000,
            reason="WebSocket stream closed",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )
        _ws_log(
            logging.INFO,
            "websocket_handler_exited",
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )
