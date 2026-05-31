"""tests/integration/test_api.py — API route integration tests"""
import httpx
import sys, pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

@pytest.fixture
async def client():
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock(return_value=None)
    redis.keys = AsyncMock(return_value=[])
    redis.hget = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    redis.hgetall = AsyncMock(return_value={})
    redis.get = AsyncMock(return_value=None)
    redis.incr = AsyncMock(return_value=1)

    with patch("redis.asyncio.from_url", return_value=redis), patch("celery.Celery"), patch("celery_app.run_swarm_task") as mt:
        mt.delay = MagicMock(return_value=MagicMock(id="mock-task"))
        from api.server import app
        app.state.redis = redis
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            c.app = app
            yield c

@pytest.fixture
def auth(): return {"x-api-key": "test-api-key"}

class TestHealth:
    async def test_200(self, client): assert (await client.get("/health")).status_code == 200
    async def test_status_ok(self, client): assert (await client.get("/health")).json().get("status") == "ok"
    async def test_no_auth_needed(self, client): assert (await client.get("/health")).status_code not in (401,403)

class TestGenerate:
    async def test_returns_job_id(self, client, auth):
        with patch("celery_app.run_swarm_task") as mt:
            mt.delay = MagicMock(return_value=MagicMock(id="t"))
            r = await client.post("/api/generate", json={"requirement":"Build a todo API with Python and Flask.","options":{}}, headers=auth)
        assert r.status_code == 202 or r.status_code == 200
        assert "job_id" in r.json()

    async def test_empty_requirement_422(self, client, auth):
        r = await client.post("/api/generate", json={"requirement":"","options":{}}, headers=auth)
        assert r.status_code == 422

    async def test_no_auth_401(self, client):
        r = await client.post("/api/generate", json={"requirement":"test","options":{}})
        assert r.status_code in (401,403)

class TestStatus:
    async def test_unknown_job_404(self, client, auth):
        client.app.state.redis.hgetall = AsyncMock(return_value={})
        r = await client.get("/api/status/nonexistent", headers=auth)
        assert r.status_code == 404

    async def test_returns_stage(self, client, auth):
        mock = {
            "job_id": "j1",
            "status": "running",
            "current_agent": "coder",
            "progress": "40",
            "created_at": "2026-05-31T00:00:00Z",
            "updated_at": "2026-05-31T00:00:00Z"
        }
        client.app.state.redis.hgetall = AsyncMock(return_value=mock)
        r = await client.get("/api/status/j1", headers=auth)
        assert r.status_code == 200
        assert r.json().get("status") == "running"

class TestOutput:
    async def test_unknown_job_404(self, client, auth):
        client.app.state.redis.hgetall = AsyncMock(return_value={})
        r = await client.get("/api/output/nonexistent", headers=auth)
        assert r.status_code == 404

    async def test_returns_files(self, client, auth):
        mock_job = {
            "job_id": "j2",
            "status": "complete",
            "github_url": "https://github.com/x/y",
            "azure_url": "https://app.azurecontainerapps.io",
            "coverage": "87",
            "created_at": "2026-05-31T00:00:00Z",
            "updated_at": "2026-05-31T00:00:00Z"
        }
        client.app.state.redis.hgetall = AsyncMock(return_value=mock_job)
        client.app.state.redis.get = AsyncMock(return_value='{"main.py": "code"}')
        r = await client.get("/api/output/j2", headers=auth)
        assert r.status_code == 200
        assert r.json().get("files") == {"main.py": "code"}
