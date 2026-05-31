"""
file_writer.py — Atomic file writer for Swarm Factory generated code.

All writes go through a temp file → verify → rename pattern so the target
location never contains a partial file if a crash or exception occurs mid-write.

Importable as:
    from tools.file_writer import write_file, write_files
"""

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def write_file(path: str, content: str) -> bool:
    """
    Write content to path atomically: temp file → verify → rename.

    Creates all parent directories automatically before writing.
    If any step fails the target file is never created / left partial.

    Args:
        path:    Destination file path (absolute or relative).
        content: Full string content to write (UTF-8 encoded).

    Returns:
        True if the file was written and verified successfully, False otherwise.
    """
    target = Path(path)
    try:
        # Ensure all parent directories exist
        target.parent.mkdir(parents=True, exist_ok=True)

        # Write to a sibling temp file in the same directory so the final
        # os.replace() is guaranteed to be atomic on POSIX systems (same device).
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.tmp_",
        )

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())  # Ensure data lands on disk before rename
        except Exception:
            # If write fails, clean up the temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Verify the temp file is readable and matches expected byte length
        written_size = os.path.getsize(tmp_path)
        expected_size = len(content.encode("utf-8"))
        if written_size != expected_size:
            os.unlink(tmp_path)
            logger.error(
                "[file_writer] Size mismatch for %s: wrote %d bytes, expected %d",
                path,
                written_size,
                expected_size,
            )
            return False

        # Atomic rename — on POSIX this is a single syscall; on Windows it
        # replaces atomically via os.replace() (unlike os.rename).
        os.replace(tmp_path, str(target))
        logger.debug("[file_writer] Wrote %s (%d bytes)", path, written_size)
        return True

    except Exception as exc:
        logger.error("[file_writer] Failed to write %s: %s", path, exc)
        return False


def write_files(files: dict[str, str], base_path: str) -> dict[str, bool]:
    """
    Write multiple files relative to base_path, creating parent dirs as needed.

    Each file is written atomically via write_file(). Failures for individual
    files are recorded but do not abort the remaining writes.

    Args:
        files:     Mapping of relative file paths to their complete string content.
        base_path: Root directory under which all files will be created.

    Returns:
        Dict mapping each original relative path to True (success) or False (failure).
    """
    base = Path(base_path)
    results: dict[str, bool] = {}

    for rel_path, content in files.items():
        abs_path = str(base / rel_path)
        success = write_file(abs_path, content)
        results[rel_path] = success
        if not success:
            logger.warning("[file_writer] Could not write file: %s", abs_path)

    total = len(files)
    succeeded = sum(results.values())
    logger.info(
        "[file_writer] write_files complete: %d/%d succeeded | base=%s",
        succeeded,
        total,
        base_path,
    )
    return results
