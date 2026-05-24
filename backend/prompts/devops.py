"""
prompts/devops.py
-----------------
Prompt templates for Dockerfile and CI/CD generation in Swarm Factory.

Each function returns a (system_prompt, user_prompt) tuple ready to pass
directly into any model's ``complete(system_prompt, user_prompt)`` method.

Usage:
    from prompts.devops import dockerfile_prompt, ci_workflow_prompt, gitignore_prompt
"""

from __future__ import annotations


_DEVOPS_SYSTEM = (
    "You are a senior DevOps engineer. "
    "You write production-ready infrastructure files with no comments, no markdown, "
    "no explanation — ONLY the raw file content. "
    "Follow security best practices: non-root users, minimal images, secret-free configs."
)


def dockerfile_prompt(
    language: str,
    framework: str,
    start_command: str,
    dependencies: list[str],
) -> tuple[str, str]:
    """
    Build prompts for generating a production Dockerfile.

    Args:
        language: Programming language, e.g. ``"Python"``.
        framework: Web framework, e.g. ``"FastAPI"``.
        start_command: Shell command to start the app,
            e.g. ``"uvicorn main:app --host 0.0.0.0 --port 8000"``.
        dependencies: List of dependency strings,
            e.g. ``["fastapi==0.104.0", "uvicorn==0.24.0"]``.

    Returns:
        Tuple of ``(system_prompt, user_prompt)``.
    """
    deps_block = "\n".join(f"  - {d}" for d in dependencies)

    user_prompt = f"""Write a production Dockerfile for a {language} {framework} app.

Start command: {start_command}

Dependencies:
{deps_block}

Rules — follow ALL of these exactly:
1. Multi-stage build: first stage installs dependencies, second stage is the runtime image.
2. Base image for both stages: python:3.11-slim
3. Create a non-root user: RUN useradd -m appuser  and  USER appuser
4. WORKDIR /app
5. EXPOSE 8000
6. HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \\
     CMD curl -f http://localhost:8000/health || exit 1
7. Copy only what is needed into the final stage — no dev tools, no test files.
8. Install dependencies from requirements.txt (write a COPY for it).
9. Final CMD must use exec form (JSON array).

Output ONLY the Dockerfile content. No markdown. No explanation. No code fences."""

    return _DEVOPS_SYSTEM, user_prompt


def ci_workflow_prompt(
    language: str,
    test_command: str,
    python_version: str = "3.11",
) -> tuple[str, str]:
    """
    Build prompts for generating a GitHub Actions CI workflow.

    Args:
        language: Programming language, e.g. ``"Python"``.
        test_command: Shell command to run the test suite,
            e.g. ``"pytest tests/ --cov=."``.
        python_version: Python version string for ``setup-python``,
            defaults to ``"3.11"``.

    Returns:
        Tuple of ``(system_prompt, user_prompt)``.
    """
    user_prompt = f"""Write a GitHub Actions CI workflow for a {language} application.

Test command: {test_command}
Python version: {python_version}

Triggers:
- push to main
- pull_request targeting main

Required steps (in order):
1. actions/checkout@v4
2. actions/setup-python@v5 with python-version: '{python_version}'
3. Cache pip packages (actions/cache@v4 with key based on requirements.txt hash)
4. Install dependencies: pip install -r requirements.txt
5. Run linter: pip install ruff && ruff check .  (continue-on-error: true)
6. Run tests: {test_command}
7. Upload coverage report (actions/upload-artifact@v4, if coverage file exists)

Workflow name: CI
Job name: test
runs-on: ubuntu-latest

Output ONLY the YAML content. No markdown. No explanation. No code fences."""

    return _DEVOPS_SYSTEM, user_prompt


def gitignore_prompt(language: str, framework: str) -> tuple[str, str]:
    """
    Build prompts for generating an appropriate .gitignore.

    Args:
        language: Programming language, e.g. ``"Python"``.
        framework: Web framework, e.g. ``"FastAPI"``.

    Returns:
        Tuple of ``(system_prompt, user_prompt)``.
    """
    user_prompt = (
        f"Write a comprehensive .gitignore file for a {language} {framework} project. "
        "Include entries for: compiled bytecode, virtual environments, IDE files "
        "(VSCode, PyCharm, vim), OS metadata (.DS_Store, Thumbs.db), environment "
        "variable files (.env, .env.*), test coverage outputs, build artifacts, "
        "and Docker build cache. "
        "Output ONLY the .gitignore content. No markdown. No explanation."
    )
    return _DEVOPS_SYSTEM, user_prompt


def readme_prompt(
    project_description: str,
    start_command: str,
    test_command: str,
    dependencies: list[str],
) -> tuple[str, str]:
    """
    Build prompts for generating a minimal project README.

    Args:
        project_description: One-sentence description of what the project does.
        start_command: How to run the application.
        test_command: How to run tests.
        dependencies: Key dependencies to mention.

    Returns:
        Tuple of ``(system_prompt, user_prompt)``.
    """
    deps_str = ", ".join(dependencies[:8])  # top 8 only
    user_prompt = (
        f"Write a concise README.md for the following project.\n\n"
        f"Description: {project_description}\n"
        f"Start command: {start_command}\n"
        f"Test command: {test_command}\n"
        f"Key dependencies: {deps_str}\n\n"
        "Include sections: Overview, Prerequisites, Installation, Running, Testing.\n"
        "Keep it under 60 lines. Output ONLY the Markdown content."
    )
    return _DEVOPS_SYSTEM, user_prompt
