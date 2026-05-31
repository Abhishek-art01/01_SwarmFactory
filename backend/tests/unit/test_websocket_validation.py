"""Unit tests for WebSocket payload validation."""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.websocket import _error_payload, _parse_client_message, _validate_job_id


def test_parse_client_message_accepts_ping():
    message, error = _parse_client_message('{"type":"ping"}')

    assert error is None
    assert message is not None
    assert message.type == "ping"


def test_parse_client_message_rejects_invalid_json():
    message, error = _parse_client_message("not-json")

    assert message is None
    assert error is not None
    assert "Invalid JSON payload" in error


def test_parse_client_message_rejects_missing_type():
    message, error = _parse_client_message('{"action":"ping"}')

    assert message is None
    assert error is not None


def test_parse_client_message_rejects_unknown_type():
    message, error = _parse_client_message('{"type":"restart"}')

    assert message is None
    assert error is not None


def test_validate_job_id_requires_uuid4():
    assert _validate_job_id(str(uuid.uuid4())) is None
    assert _validate_job_id("not-a-uuid") == "job_id must be a valid UUID4"


def test_error_payload_is_client_safe_json():
    payload = json.loads(_error_payload("invalid_message", "Invalid JSON payload"))

    assert payload == {
        "type": "error",
        "error_type": "invalid_message",
        "message": "Invalid JSON payload",
    }
