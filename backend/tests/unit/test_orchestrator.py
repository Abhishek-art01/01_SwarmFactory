"""tests/unit/test_orchestrator.py — quality_gate, merger, fallback_chain, exceptions"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestQualityGate:
    def test_passes_score_7(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 70})
        assert passed is True
        assert len(issues) == 0

    def test_passes_score_5(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 50})
        assert passed is True
        assert len(issues) == 0

    def test_fails_score_4(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 40})
        assert passed is False
        assert len(issues) > 0
        assert any("Review score" in iss for iss in issues)

    def test_fails_score_0(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 0})
        assert passed is False
        assert len(issues) > 0
        assert any("Review score" in iss for iss in issues)

    def test_passes_score_10(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 100})
        assert passed is True
        assert len(issues) == 0

    def test_normalizes_reviewer_score_out_of_10(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 7})
        assert passed is True
        assert len(issues) == 0

    def test_normalizes_low_reviewer_score_out_of_10(self):
        from orchestrator.quality_gate import check_quality
        passed, issues = check_quality({"main.py": "print('ok')"}, {"score": 4})
        assert passed is False
        assert any("Review score 40/100" in iss for iss in issues)


class TestParallelRunner:
    @pytest.mark.asyncio
    async def test_test_and_reviewer_receive_coder_output(self, monkeypatch):
        from orchestrator import parallel_runner

        calls = []
        coder_output = {
            "files": {"main.py": "print('ok')"},
            "dependencies": ["fastapi==0.104.0"],
            "entry_point": "main.py",
            "start_command": "python main.py",
        }

        class FakeCoder:
            async def run(self, input_data, **kwargs):
                calls.append("coder")
                return coder_output

        class FakeTest:
            async def run(self, input_data, **kwargs):
                calls.append("test")
                assert input_data["coder"] == coder_output
                assert input_data["coder"]["files"] == coder_output["files"]
                return SimpleNamespace(test_files={"tests/test_main.py": "def test_ok(): pass"})

        class FakeReviewer:
            async def run(self, input_data, **kwargs):
                calls.append("reviewer")
                assert input_data == coder_output
                return {"score": 7, "issues": [], "coverage": 0}

        async def fake_with_fallback(agent_fn, *args, **kwargs):
            return await agent_fn(*args)

        monkeypatch.setattr(parallel_runner, "coder_agent", FakeCoder())
        monkeypatch.setattr(parallel_runner, "test_agent", FakeTest())
        monkeypatch.setattr(parallel_runner, "reviewer_agent", FakeReviewer())
        monkeypatch.setattr(parallel_runner, "with_fallback", fake_with_fallback)

        result = await parallel_runner.run_parallel_agents(
            architecture={"files": ["main.py"]},
            task_graph={"tasks": []},
            job_id="job-1",
            redis=None,
        )

        assert calls[0] == "coder"
        assert set(calls[1:]) == {"test", "reviewer"}
        assert result["code_files"] == coder_output["files"]
        assert result["test_files"] == {"tests/test_main.py": "def test_ok(): pass"}
        assert result["review_result"]["score"] == 7

class TestMerger:
    def test_combines_two_dicts(self):
        from orchestrator.merger import merge_outputs
        a = {"main.py": "code"}
        b = {"tests/t.py": "test"}
        m = merge_outputs(a, b, job_id="j1")
        assert "main.py" in m and "tests/t.py" in m

    def test_empty_dicts(self):
        from orchestrator.merger import merge_outputs
        assert merge_outputs({}, {}, job_id="j") == {}

    def test_conflict_first_wins(self):
        from orchestrator.merger import merge_outputs
        a = {"f.py": "v=1\n"}
        b = {"f.py": "v=99\n"}
        m = merge_outputs(a, b, job_id="j")
        assert m["f.py"] == "v=1\n"

class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_returns_on_success(self):
        from orchestrator.fallback_chain import with_fallback
        async def fn(data): return {"ok": True}
        r = await with_fallback(fn, {}, job_id="j")
        assert r["ok"] is True

    @pytest.mark.asyncio
    async def test_falls_back_on_failure(self):
        from orchestrator.fallback_chain import with_fallback
        calls = {"n":0}
        async def fn(data):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("fail")
            return {"n": calls["n"]}
        r = await with_fallback(fn, {}, job_id="j")
        assert r["n"] == 2

    @pytest.mark.asyncio
    async def test_returns_something_if_all_fail(self):
        from orchestrator.fallback_chain import with_fallback
        async def fn(data): raise Exception("always fails")
        with pytest.raises(RuntimeError):
            await with_fallback(fn, {}, job_id="j")

class TestExceptions:
    def test_quality_gate_error(self):
        from core.exceptions import QualityGateError
        e = QualityGateError(score=3, issues=[{"i":"sql injection"}])
        assert e.score == 3

    def test_job_not_found(self):
        from core.exceptions import JobNotFoundError
        e = JobNotFoundError("abc-123")
        assert e.job_id == "abc-123" and "abc-123" in str(e)

    def test_agent_error(self):
        from core.exceptions import AgentError
        e = AgentError("coder","timeout")
        assert e.agent_name == "coder"

    def test_all_inherit_base(self):
        from core.exceptions import SwarmFactoryError, QualityGateError, JobNotFoundError, AgentError
        for cls in [QualityGateError, JobNotFoundError, AgentError]:
            assert issubclass(cls, SwarmFactoryError)
