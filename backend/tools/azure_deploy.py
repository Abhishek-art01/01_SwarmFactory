"""
tools/azure_deploy.py
---------------------
Azure Container Apps deployment tool for Swarm Factory.

Deploys a container image to Azure Container Apps using the Azure SDK.
Falls back to an ``az`` CLI subprocess if the SDK path is unavailable.

Usage:
    from tools.azure_deploy import deploy_to_container_apps
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 10   # seconds between status checks
_MAX_POLL_WAIT = 300  # 5 minutes timeout


class AzureDeployError(Exception):
    """Raised when deployment to Azure Container Apps fails."""


def deploy_to_container_apps(
    image_uri: str,
    app_name: str,
    resource_group: str,
) -> str:
    """
    Deploy a container image to Azure Container Apps.

    Uses the Azure SDK (azure-mgmt-containerinstance) to create or update a
    container group.  If the SDK call fails, falls back to the ``az`` CLI.

    Args:
        image_uri: Full image URI, e.g.
            ``"yourregistry.azurecr.io/my-app:latest"``.
        app_name: Name for the Container App / container group.
        resource_group: Azure resource group name.

    Returns:
        Public HTTPS URL for the deployed app, e.g.
        ``"https://my-app.azurecontainerapps.io"``.

    Raises:
        AzureDeployError: If all deployment attempts fail.
    """
    logger.info(
        "Starting Azure deployment",
        extra={"app": app_name, "image": image_uri, "rg": resource_group},
    )

    try:
        url = _deploy_via_sdk(image_uri, app_name, resource_group)
        logger.info("Azure SDK deployment succeeded", extra={"url": url})
        return url
    except AzureDeployError:
        raise
    except Exception as exc:
        logger.warning(
            "Azure SDK deploy failed — falling back to CLI",
            extra={"error": str(exc)},
        )

    return _deploy_via_cli(image_uri, app_name, resource_group)


# ── SDK path ──────────────────────────────────────────────────────────────────

def _deploy_via_sdk(image_uri: str, app_name: str, resource_group: str) -> str:
    """
    Deploy using azure-mgmt-containerinstance SDK.

    Args:
        image_uri: Full image URI.
        app_name: Container group / app name.
        resource_group: Azure resource group.

    Returns:
        Public HTTPS URL.

    Raises:
        AzureDeployError: If the SDK call fails.
    """
    subscription_id = _require_env("AZURE_SUBSCRIPTION_ID")
    registry = _require_env("AZURE_CONTAINER_REGISTRY")
    registry_user = os.environ.get("AZURE_REGISTRY_USERNAME", "")
    registry_password = os.environ.get("AZURE_REGISTRY_PASSWORD", "")

    try:
        from azure.core.exceptions import AzureError
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.containerinstance import ContainerInstanceManagementClient
        from azure.mgmt.containerinstance.models import (
            Container,
            ContainerGroup,
            ContainerGroupRestartPolicy,
            ContainerPort,
            ImageRegistryCredential,
            IpAddress,
            OperatingSystemTypes,
            ResourceRequests,
            ResourceRequirements,
        )

        credential = DefaultAzureCredential()
        client = ContainerInstanceManagementClient(credential, subscription_id)

        registry_creds: list[ImageRegistryCredential] = []
        if registry_user and registry_password:
            registry_creds.append(
                ImageRegistryCredential(
                    server=registry,
                    username=registry_user,
                    password=registry_password,
                )
            )

        container_group = ContainerGroup(
            location=os.environ.get("AZURE_LOCATION", "eastus"),
            containers=[
                Container(
                    name=app_name,
                    image=image_uri,
                    resources=ResourceRequirements(
                        requests=ResourceRequests(cpu=1.0, memory_in_gb=1.5)
                    ),
                    ports=[ContainerPort(port=8000)],
                )
            ],
            os_type=OperatingSystemTypes.LINUX,
            restart_policy=ContainerGroupRestartPolicy.ON_FAILURE,
            ip_address=IpAddress(
                ports=[ContainerPort(port=8000)],
                type="Public",
                dns_name_label=app_name,
            ),
            image_registry_credentials=registry_creds or None,
        )

        logger.info(
            "Creating/updating container group via SDK",
            extra={"app": app_name, "rg": resource_group},
        )
        poller = client.container_groups.begin_create_or_update(
            resource_group, app_name, container_group
        )
        result = poller.result(timeout=_MAX_POLL_WAIT)

        fqdn = result.ip_address.fqdn if result.ip_address else None
        if not fqdn:
            raise AzureDeployError(
                f"Container group '{app_name}' has no public FQDN after deployment"
            )

        return f"https://{fqdn}"

    except AzureDeployError:
        raise
    except ImportError as exc:
        raise RuntimeError(f"Azure SDK packages are not installed: {exc}") from exc
    except AzureError as exc:
        raise AzureDeployError(f"Azure SDK error: {exc}") from exc


# ── CLI fallback ───────────────────────────────────────────────────────────────

def _deploy_via_cli(image_uri: str, app_name: str, resource_group: str) -> str:
    """
    Deploy using the ``az containerapp`` CLI command.

    Args:
        image_uri: Full image URI.
        app_name: Container App name.
        resource_group: Azure resource group.

    Returns:
        Public HTTPS URL.

    Raises:
        AzureDeployError: If the CLI command fails.
    """
    env_name = _require_env("AZURE_CONTAINER_APP_ENV")
    registry = _require_env("AZURE_CONTAINER_REGISTRY")
    registry_user = os.environ.get("AZURE_REGISTRY_USERNAME", "")
    registry_password = os.environ.get("AZURE_REGISTRY_PASSWORD", "")

    cmd = [
        "az", "containerapp", "create",
        "--name", app_name,
        "--resource-group", resource_group,
        "--environment", env_name,
        "--image", image_uri,
        "--target-port", "8000",
        "--ingress", "external",
        "--min-replicas", "1",
        "--max-replicas", "3",
        "--query", "properties.configuration.ingress.fqdn",
        "--output", "tsv",
    ]

    if registry_user and registry_password:
        cmd += [
            "--registry-server", registry,
            "--registry-username", registry_user,
            "--registry-password", registry_password,
        ]

    logger.info(
        "Deploying via az CLI",
        extra={"app": app_name, "rg": resource_group},
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_MAX_POLL_WAIT,
        )
        if result.returncode != 0:
            raise AzureDeployError(
                f"az containerapp create failed (exit {result.returncode}):\n"
                f"{result.stderr}"
            )

        fqdn = result.stdout.strip()
        if not fqdn:
            raise AzureDeployError(
                f"az CLI returned empty FQDN for app '{app_name}'"
            )

        url = f"https://{fqdn}"
        logger.info("CLI deployment succeeded", extra={"url": url})
        return url

    except subprocess.TimeoutExpired as exc:
        raise AzureDeployError(
            f"az containerapp create timed out after {_MAX_POLL_WAIT}s"
        ) from exc
    except FileNotFoundError as exc:
        raise AzureDeployError("'az' CLI not found on PATH") from exc


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    """
    Return an environment variable value or raise AzureDeployError.

    Args:
        name: Variable name.

    Returns:
        Variable value.

    Raises:
        AzureDeployError: If the variable is unset or empty.
    """
    value = os.environ.get(name, "")
    if not value:
        raise AzureDeployError(f"Required environment variable '{name}' is not set")
    return value
