"""
test_runner.py — pytest + coverage runner for Swarm Factory generated projects.

Executes pytest with coverage reporting in a subprocess so that test results
and coverage percentages can be consumed programmatically by the pipeline.

Importable as:
    from tools.test_runner import run_tests, TestResult
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestResult(BaseModel):
    """
    Structured result returned by run_tests().

    Attributes:
        passed:       True if the pytest run exited with code 0 (all tests pass).
        coverage:     Line coverage percentage as a float between 0.0 and 100.0.
        total_tests:  Total number of tests collected and run.
        passed_tests: Number of tests that passed.
        failed_tests: Number of tests that failed or errored.
        output:       Full combined stdout from pytest (includes coverage table).
        errors:       List of individual test-failure summary lines extracted
                      from the pytest output.
    """

    passed: bool
    coverage: float
    total_tests: int
    passed_tests: int
    failed_tests: int
    output: str
    errors: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_coverage(output: str) -> float:
    """
    Extract the total coverage percentage from pytest-cov's terminal output.

    Looks for a line like ``TOTAL    1234   123    90%`` at the bottom of the
    coverage table.

    Args:
        output: Full stdout string from the pytest run.

    Returns:
        Coverage as a float (0.0–100.0), or 0.0 if not found.
    """
    # pytest-cov prints: TOTAL   <stmts>  <miss>  <cover>%
    match = re.search(r"TOTAL\s+\d+\s+\d+\s+([\d.]+)%", output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def _parse_test_counts(output: str) -> tuple[int, int, int]:
    """
    Parse the pytest summary line to extract passed, failed, and total counts.

    Handles output like:
        ``5 passed, 2 failed in 1.23s``
        ``7 passed in 0.45s``

    Args:
        output: Full stdout string from the pytest run.

    Returns:
        Tuple of (total_tests, passed_tests, failed_tests).
    """
    passed = 0
    failed = 0

    passed_match = re.search(r"(\d+) passed", output)
    if passed_match:
        passed = int(passed_match.group(1))

    failed_match = re.search(r"(\d+) failed", output)
    if failed_match:
        failed = int(failed_match.group(1))

    # Also count errors as failures
    error_match = re.search(r"(\d+) error", output)
    if error_match:
        failed += int(error_match.group(1))

    total = passed + failed
    return total, passed, failed


def _extract_error_messages(output: str) -> list[str]:
    """
    Pull individual FAILED / ERROR lines from pytest output.

    These are the short one-line summaries at the bottom of a run, e.g.:
        ``FAILED tests/test_main.py::test_create_user - AssertionError``

    Args:
        output: Full stdout string from the pytest run.

    Returns:
        List of failure/error summary strings.
    """
    errors: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            errors.append(stripped)
    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_tests(project_path: str) -> TestResult:
    """
    Run pytest with line-coverage reporting on a generated project.

    Discovers tests under a ``tests/`` subdirectory (or the project root if
    no ``tests/`` dir exists) and measures coverage over the whole project.
    Both stdout and stderr are captured and merged into ``TestResult.output``.

    Args:
        project_path: Absolute or relative path to the root of the generated
                      project (the directory that contains ``tests/`` and the
                      source files).

    Returns:
        A populated TestResult instance.
    """
    root = Path(project_path)
    if not root.exists():
        logger.error("[test_runner] Project path not found: %s", project_path)
        return TestResult(
            passed=False,
            coverage=0.0,
            total_tests=0,
            passed_tests=0,
            failed_tests=0,
            output=f"Project path not found: {project_path}",
            errors=[f"Project path not found: {project_path}"],
        )

    # Prefer running tests from a ``tests/`` subdirectory if it exists
    tests_dir = root / "tests"
    test_target = str(tests_dir) if tests_dir.is_dir() else str(root)

    cmd = [
        sys.executable, "-m", "pytest",
        test_target,
        f"--cov={root}",
        "--cov-report=term-missing",
        "--tb=short",          # Short traceback — enough for error summaries
        "-q",                  # Quieter output, easier to parse
        "--no-header",
    ]

    logger.info("[test_runner] Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,       # 2-minute hard ceiling for the whole test suite
            cwd=str(root),
        )
    except subprocess.TimeoutExpired as exc:
        timeout_output = (
            (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            + (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
        )
        logger.error("[test_runner] pytest timed out for %s", project_path)
        return TestResult(
            passed=False,
            coverage=0.0,
            total_tests=0,
            passed_tests=0,
            failed_tests=0,
            output=f"pytest timed out after 120s\n{timeout_output}",
            errors=["pytest timed out after 120s"],
        )
    except Exception as exc:
        logger.error("[test_runner] Unexpected error: %s", exc)
        return TestResult(
            passed=False,
            coverage=0.0,
            total_tests=0,
            passed_tests=0,
            failed_tests=0,
            output=str(exc),
            errors=[str(exc)],
        )

    # Merge stdout + stderr — pytest-cov writes the coverage table to stdout
    # but some warnings/import errors go to stderr
    combined_output = result.stdout
    if result.stderr.strip():
        combined_output += "\n--- STDERR ---\n" + result.stderr

    coverage = _parse_coverage(combined_output)
    total, passed_count, failed_count = _parse_test_counts(combined_output)
    errors = _extract_error_messages(combined_output)

    # pytest exits 0 only when all tests pass and no errors occurred
    all_passed = result.returncode == 0

    logger.info(
        "[test_runner] Done | passed=%s | total=%d | passed=%d | failed=%d | coverage=%.1f%%",
        all_passed,
        total,
        passed_count,
        failed_count,
        coverage,
    )

    return TestResult(
        passed=all_passed,
        coverage=coverage,
        total_tests=total,
        passed_tests=passed_count,
        failed_tests=failed_count,
        output=combined_output,
        errors=errors,
    )
