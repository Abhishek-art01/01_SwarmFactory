"""tests/conftest.py — shared pytest fixtures"""
import json, os, sys, tempfile, pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_KEY",  "test-key-00000000000000000000000000000000")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o")
os.environ.setdefault("REDIS_URL",   "redis://localhost:6379/0")
os.environ.setdefault("API_KEY",     "test-api-key")
os.environ.setdefault("SECRET_KEY",  "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("APP_ENV",     "development")
os.environ.setdefault("LLM_PROVIDER", "azure")
os.environ.setdefault("SESSION_STORE_PATH", str(Path(tempfile.gettempdir()) / "sf_test_sessions"))

@pytest.fixture
def tmp_dir(tmp_path): return tmp_path

@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "sessions"; d.mkdir()
    import memory.session_store
    orig_session_dir = memory.session_store._SESSION_DIR
    memory.session_store._SESSION_DIR = d
    orig = os.environ.get("SESSION_STORE_PATH")
    os.environ["SESSION_STORE_PATH"] = str(d)
    yield d
    memory.session_store._SESSION_DIR = orig_session_dir
    if orig is None:
        os.environ.pop("SESSION_STORE_PATH", None)
    else:
        os.environ["SESSION_STORE_PATH"] = orig

@pytest.fixture
def sample_requirement():
    return "Build a REST API for user authentication with JWT using FastAPI and PostgreSQL."

@pytest.fixture
def sample_code_files():
    return {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'status': 'ok'}\n",
        "models/user.py": "from pydantic import BaseModel\nclass User(BaseModel):\n    id: str\n    email: str\n",
    }

@pytest.fixture
def sample_review_output():
    return {"score": 7, "approved": True,
            "issues": [{"file":"main.py","line":None,"severity":"low","issue":"Missing rate limiting","fix":"Add slowapi"}],
            "summary": "Code is clean with minor improvements."}
