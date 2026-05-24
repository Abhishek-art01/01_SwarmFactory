"""
tools/docker_builder.py
-----------------------
Docker image build and push operations for Swarm Factory.

Builds a Docker image from the generated project directory, pushes it to
Azure Container Registry, then removes the local image to reclaim disk space.

Usage:
    from tools.docker_builder import build_and_push
"""

import logging
import os

import docker
from docker.errors import BuildError, APIError, ImageNotFound

logger = logging.getLogger(__name__)


class DockerBuildError(Exception):
    """Raised when Docker build or push fails."""


def build_and_push(project_path: str, image_tag: str, registry: str) -> str:
    """
    Build a Docker image and push it to a container registry.

    Steps
    -----
    1. ``docker build -t {registry}/{image_tag}:latest {project_path}``
    2. ``docker push {registry}/{image_tag}:latest``
    3. Remove the local image to free disk space.

    Args:
        project_path: Absolute path to the directory containing the Dockerfile.
        image_tag: Image name/tag (without registry prefix), e.g. ``"my-app"``.
        registry: Container registry host, e.g.
            ``"yourregistry.azurecr.io"``.

    Returns:
        Full image URI: ``"{registry}/{image_tag}:latest"``.

    Raises:
        DockerBuildError: If build, push, or any Docker API call fails.
    """
    full_image_uri = f"{registry}/{image_tag}:latest"

    client = _get_docker_client()
    _build_image(client, project_path, full_image_uri)
    _push_image(client, full_image_uri, registry)
    _remove_local_image(client, full_image_uri)

    logger.info(
        "Docker image built and pushed",
        extra={"image_uri": full_image_uri},
    )
    return full_image_uri


# ── internals ─────────────────────────────────────────────────────────────────

def _get_docker_client() -> docker.DockerClient:
    """
    Return a Docker client connected to the local daemon.

    Raises:
        DockerBuildError: If the Docker daemon is not reachable.
    """
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:
        raise DockerBuildError(f"Cannot connect to Docker daemon: {exc}") from exc


def _build_image(
    client: docker.DockerClient, project_path: str, full_image_uri: str
) -> None:
    """
    Build the Docker image.

    Args:
        client: Active Docker client.
        project_path: Build context directory (must contain a Dockerfile).
        full_image_uri: Full image tag including registry.

    Raises:
        DockerBuildError: If the build fails.
    """
    logger.info(
        "Building Docker image",
        extra={"image": full_image_uri, "context": project_path},
    )
    try:
        image, build_logs = client.images.build(
            path=project_path,
            tag=full_image_uri,
            rm=True,           # remove intermediate containers
            pull=True,         # always pull fresh base image
            nocache=False,
        )
        for chunk in build_logs:
            if "stream" in chunk:
                line = chunk["stream"].strip()
                if line:
                    logger.debug("Docker build: %s", line)

    except BuildError as exc:
        log_lines = "\n".join(
            chunk.get("stream", "") for chunk in exc.build_log
            if isinstance(chunk, dict)
        )
        raise DockerBuildError(
            f"Docker build failed for image '{full_image_uri}':\n{log_lines}"
        ) from exc
    except APIError as exc:
        raise DockerBuildError(
            f"Docker API error during build: {exc.explanation}"
        ) from exc


def _push_image(
    client: docker.DockerClient, full_image_uri: str, registry: str
) -> None:
    """
    Push the image to the container registry.

    Uses the ``AZURE_CONTAINER_REGISTRY`` credentials baked into the local
    Docker credential store (populated by ``az acr login`` in the CI workflow).

    Args:
        client: Active Docker client.
        full_image_uri: Full ``registry/name:tag`` URI.
        registry: Registry hostname (used in log messages).

    Raises:
        DockerBuildError: If the push fails.
    """
    logger.info(
        "Pushing Docker image to registry",
        extra={"image": full_image_uri, "registry": registry},
    )
    try:
        push_output = client.images.push(
            full_image_uri,
            stream=True,
            decode=True,
        )
        for chunk in push_output:
            if "error" in chunk:
                raise DockerBuildError(
                    f"Docker push error: {chunk['error']}"
                )
            if "status" in chunk:
                logger.debug("Docker push: %s", chunk.get("status", ""))

    except DockerBuildError:
        raise
    except APIError as exc:
        raise DockerBuildError(
            f"Docker API error during push of '{full_image_uri}': {exc.explanation}"
        ) from exc


def _remove_local_image(client: docker.DockerClient, full_image_uri: str) -> None:
    """
    Remove the local Docker image to reclaim disk space.

    Failure here is logged but does NOT raise — freeing disk is best-effort.

    Args:
        client: Active Docker client.
        full_image_uri: Full image URI to remove.
    """
    try:
        client.images.remove(image=full_image_uri, force=True)
        logger.info(
            "Local Docker image removed",
            extra={"image": full_image_uri},
        )
    except ImageNotFound:
        logger.warning(
            "Local image not found for cleanup — skipping",
            extra={"image": full_image_uri},
        )
    except APIError as exc:
        logger.warning(
            "Failed to remove local Docker image",
            extra={"image": full_image_uri, "error": str(exc)},
        )
