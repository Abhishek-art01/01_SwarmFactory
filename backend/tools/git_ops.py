"""
tools/git_ops.py
----------------
GitHub repository creation and push operations for Swarm Factory.

Creates a new GitHub repo, initialises a local git repo from the generated
codebase, and pushes it.  Uses PyGithub for the API calls and subprocess
git commands for local operations (avoids GitPython's heavy dependency).

Usage:
    from tools.git_ops import create_repo_and_push
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from github import Github, GithubException

logger = logging.getLogger(__name__)


class GitOpsError(Exception):
    """Raised when any git or GitHub operation fails."""


def create_repo_and_push(
    local_path: str,
    repo_name: str,
    description: str = "",
) -> str:
    """
    Create a GitHub repo and push the contents of ``local_path`` to it.

    Steps
    -----
    1. Create a new GitHub repo via the PyGithub API.
    2. ``git init`` in ``local_path``.
    3. ``git add .`` — stage all files.
    4. ``git commit -m "Initial commit by Swarm Factory"``.
    5. ``git remote add origin <clone_url>``.
    6. ``git push -u origin main``.

    Args:
        local_path: Absolute path to the directory containing the project files.
        repo_name: Name for the new GitHub repository.
        description: Optional repository description.

    Returns:
        Full GitHub repository URL, e.g.
        ``"https://github.com/your-org/repo-name"``.

    Raises:
        GitOpsError: If any step (API call or git command) fails.
    """
    token = _require_env("GITHUB_TOKEN")
    org = _require_env("GITHUB_ORG")

    repo_url, clone_url = _create_github_repo(token, org, repo_name, description)
    _git_init_commit_push(local_path, clone_url, token)

    logger.info(
        "Repository pushed successfully",
        extra={"repo_url": repo_url, "path": local_path},
    )
    return repo_url


# ── internals ─────────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    """
    Return the value of an environment variable or raise GitOpsError.

    Args:
        name: Environment variable name.

    Returns:
        Variable value as a string.

    Raises:
        GitOpsError: If the variable is not set or empty.
    """
    value = os.environ.get(name, "")
    if not value:
        raise GitOpsError(f"Required environment variable '{name}' is not set")
    return value


def _create_github_repo(
    token: str, org: str, repo_name: str, description: str
) -> tuple[str, str]:
    """
    Create a new private GitHub repo and return (html_url, clone_url).

    Args:
        token: GitHub personal access token.
        org: GitHub username or organisation name.
        repo_name: Repository name.
        description: Repository description.

    Returns:
        Tuple of (html_url, clone_url_with_auth).

    Raises:
        GitOpsError: If the API call fails.
    """
    try:
        gh = Github(token)
        user = gh.get_user()

        logger.info(
            "Creating GitHub repository",
            extra={"org": org, "repo": repo_name},
        )

        # Try org first; fall back to personal account.
        try:
            owner = gh.get_organization(org)
        except GithubException:
            owner = user

        repo = owner.create_repo(
            name=repo_name,
            description=description,
            private=True,
            auto_init=False,
        )

        # Embed token in clone URL for push auth over HTTPS.
        clone_url = repo.clone_url.replace(
            "https://", f"https://{token}@"
        )
        logger.info(
            "GitHub repo created",
            extra={"html_url": repo.html_url},
        )
        return repo.html_url, clone_url

    except GithubException as exc:
        raise GitOpsError(
            f"Failed to create GitHub repo '{repo_name}': {exc.data}"
        ) from exc


def _git_init_commit_push(local_path: str, clone_url: str, token: str) -> None:
    """
    Initialise a git repo in ``local_path``, commit all files, and push.

    Args:
        local_path: Directory containing generated project files.
        clone_url: HTTPS clone URL (with embedded token).
        token: GitHub token (used in git credential config).

    Raises:
        GitOpsError: If any git command exits non-zero.
    """
    path = Path(local_path)
    if not path.is_dir():
        raise GitOpsError(f"local_path does not exist or is not a directory: {local_path}")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Swarm Factory",
        "GIT_AUTHOR_EMAIL": "swarm@factory.ai",
        "GIT_COMMITTER_NAME": "Swarm Factory",
        "GIT_COMMITTER_EMAIL": "swarm@factory.ai",
    }

    steps: list[tuple[str, list[str]]] = [
        ("git init", ["git", "init", "-b", "main"]),
        ("git add", ["git", "add", "."]),
        ("git commit", ["git", "commit", "-m", "Initial commit by Swarm Factory"]),
        ("git remote add", ["git", "remote", "add", "origin", clone_url]),
        ("git push", ["git", "push", "-u", "origin", "main"]),
    ]

    for step_name, cmd in steps:
        logger.info("Running git step", extra={"step": step_name, "path": local_path})
        try:
            result = subprocess.run(
                cmd,
                cwd=str(path),
                env=git_env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                # Mask token in error output
                stderr = result.stderr.replace(
                    os.environ.get("GITHUB_TOKEN", "TOKEN"), "***"
                )
                raise GitOpsError(
                    f"Git step '{step_name}' failed (exit {result.returncode}):\n{stderr}"
                )
        except FileNotFoundError as exc:
            raise GitOpsError("'git' executable not found on PATH") from exc
