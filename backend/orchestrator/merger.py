"""
orchestrator/merger.py
-----------------------
Combines and deduplicates the final codebase from mediator_agent with
the test files from test_agent.

Merge rules:
  1. All files from mediator output take precedence.
  2. Test files are added with a 'tests/' prefix if not already prefixed.
  3. Duplicate filenames: mediator wins (it has reviewed all outputs).
  4. Empty files from either source are dropped.
"""

import logging

logger = logging.getLogger(__name__)


def merge_outputs(
    mediator_codebase: dict[str, str],
    test_files: dict[str, str],
    job_id: str = "",
) -> dict[str, str]:
    """
    Merge mediator output with test files into a single codebase dict.

    Args:
        mediator_codebase: { filename: code } from mediator_agent.
        test_files:        { filename: code } from test_agent.
        job_id:            UUID4 for logging.

    Returns:
        dict[str, str]: Merged { filename: code } with no empty files.
    """
    merged: dict[str, str] = {}

    # Add mediator files first (they take precedence)
    for filename, content in mediator_codebase.items():
        if content.strip():
            merged[filename] = content
        else:
            logger.debug("Dropping empty mediator file", extra={"job_id": job_id, "file": filename})

    # Add test files, prefixing with 'tests/' if not already placed there
    for filename, content in test_files.items():
        if not content.strip():
            continue

        # Normalise test file path
        if not filename.startswith("tests/") and not filename.startswith("test_"):
            dest = f"tests/{filename}"
        else:
            dest = filename

        # Mediator takes precedence — only add if not already present
        if dest not in merged:
            merged[dest] = content
        else:
            logger.debug(
                "Test file skipped (mediator version exists)",
                extra={"job_id": job_id, "file": dest},
            )

    logger.info(
        "Merge complete",
        extra={
            "job_id": job_id,
            "mediator_files": len(mediator_codebase),
            "test_files": len(test_files),
            "merged_total": len(merged),
        },
    )

    return merged
