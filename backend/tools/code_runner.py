"""
code_runner.py — Subprocess runner for Swarm Factory generated Python code.

Executes a generated Python file in an isolated subprocess with a configurable
timeout, capturing stdout, stderr, and exit code for pipeline inspection.

Importable as:
    from tools.code_runner import run_code
"""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def run_code(filepath: str, timeout: int = 10) -> dict:
    """
    Execute a Python file in a subprocess and capture its output.

    Uses the same Python interpreter that is running the current process
    (``sys.executable``) to avoid virtual-environment mismatches.

    Args:
        filepath: Absolute or relative path to the Python file to run.
        timeout:  Maximum seconds to wait before killing the process (default 10).

    Returns:
        Dict with keys:
            - ``returncode`` (int)  : Process exit code; 0 means success.
            - ``stdout``     (str)  : Captured standard output.
            - ``stderr``     (str)  : Captured standard error.
            - ``timed_out``  (bool) : True if the process was killed due to timeout.
    """
    path = Path(filepath)
    if not path.exists():
        logger.warning("[code_runner] File not found: %s", filepath)
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"File not found: {filepath}",
            "timed_out": False,
        }

    logger.debug("[code_runner] Running %s (timeout=%ds)", filepath, timeout)

    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            # Run from the file's directory so relative imports resolve correctly
            cwd=str(path.parent),
        )
        logger.debug(
            "[code_runner] %s exited with code %d | stdout_len=%d | stderr_len=%d",
            filepath,
            result.returncode,
            len(result.stdout),
            len(result.stderr),
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": False,
        }

    except subprocess.TimeoutExpired as exc:
        # Kill the process group so child threads/processes also die
        logger.warning("[code_runner] %s timed out after %ds", filepath, timeout)
        return {
            "returncode": -1,
            "stdout": exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "",
            "stderr": exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "",
            "timed_out": True,
        }

    except Exception as exc:
        logger.error("[code_runner] Unexpected error running %s: %s", filepath, exc)
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }
