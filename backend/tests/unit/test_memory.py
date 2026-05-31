"""tests/unit/test_memory.py — session_store, context_injector"""
import json, sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestSessionStore:
    def test_save_load_roundtrip(self, session_dir):
        from memory.session_store import save, load
        data = {"job_id":"t1","requirement":"build API","status":"complete"}
        assert save("t1", data) is True
        loaded = load("t1")
        assert loaded is not None
        assert loaded["job_id"] == "t1"

    def test_load_nonexistent_returns_none(self, session_dir):
        from memory.session_store import load
        assert load("does-not-exist-xyz") is None

    def test_idempotent_save(self, session_dir):
        from memory.session_store import save, load
        save("idem", {"v":1}); save("idem", {"v":1})
        assert load("idem") is not None

    def test_overwrite(self, session_dir):
        from memory.session_store import save, load
        save("ow", {"v":1}); save("ow", {"v":2})
        assert load("ow")["v"] == 2

    def test_list_sessions(self, session_dir):
        from memory.session_store import save, list_sessions
        save("la",{"x":1}); save("lb",{"x":2})
        sessions = list_sessions()
        assert "la" in sessions and "lb" in sessions

    def test_delete(self, session_dir):
        from memory.session_store import save, load, delete
        save("del",{"x":1})
        assert delete("del") is True
        assert load("del") is None

    def test_delete_nonexistent_returns_false(self, session_dir):
        from memory.session_store import delete
        assert delete("nope-abc") is False

    def test_file_is_valid_json(self, session_dir):
        from memory.session_store import save
        save("json-check",{"key":"val","n":42})
        f = session_dir / "json-check.json"
        assert f.exists()
        assert json.load(open(f))["n"] == 42

class TestContextInjector:
    def test_returns_string(self, session_dir):
        from memory.context_injector import get_relevant_context
        assert isinstance(get_relevant_context("build a FastAPI app"), str)

    def test_empty_sessions_returns_string(self, session_dir):
        from memory.context_injector import get_relevant_context
        assert isinstance(get_relevant_context("anything"), str)

    def test_save_context_returns_bool(self, session_dir):
        from memory.context_injector import save_context
        assert isinstance(save_context("j1","build API",{"language":"python"}), bool)
