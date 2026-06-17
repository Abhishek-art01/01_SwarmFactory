import asyncio
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state() -> dict[str, dict[str, Any]]:
    return {
        "projects": {},
        "workspaces": {},
        "conversations": {},
        "messages": {},
        "files": {},
    }


class ProjectHistoryStoreError(RuntimeError):
    """Raised when persistent project history cannot be read or written."""


class AzureBlobProjectHistoryStore:
    """Azure Blob backed JSON document store for project chat history."""

    def __init__(
        self,
        connection_string: str | None = None,
        container_name: str | None = None,
        blob_name: str | None = None,
    ) -> None:
        self.connection_string = connection_string if connection_string is not None else settings.AZURE_STORAGE_CONNECTION_STRING
        self.container_name = container_name or settings.AZURE_STORAGE_CONTAINER
        self.blob_name = blob_name or settings.PROJECT_HISTORY_BLOB_NAME
        self._blob_client: Any = None
        self._lock = asyncio.Lock()

    def _client(self) -> Any:
        if not self.connection_string:
            raise ProjectHistoryStoreError(
                "AZURE_STORAGE_CONNECTION_STRING is required for project chat history persistence."
            )

        if self._blob_client is None:
            try:
                from azure.storage.blob import BlobServiceClient
            except ImportError as exc:
                raise ProjectHistoryStoreError(
                    "azure-storage-blob is required for project chat history persistence."
                ) from exc

            service = BlobServiceClient.from_connection_string(self.connection_string)
            container = service.get_container_client(self.container_name)
            try:
                container.create_container()
            except Exception:
                pass
            self._blob_client = container.get_blob_client(self.blob_name)

        return self._blob_client

    def _load_sync(self) -> dict[str, dict[str, Any]]:
        try:
            raw = self._client().download_blob().readall()
        except Exception as exc:
            if exc.__class__.__name__ == "ResourceNotFoundError":
                return empty_state()
            logger.error("Failed to load project history from Azure Blob", extra={"error": str(exc)})
            raise ProjectHistoryStoreError("Could not load project history.") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ProjectHistoryStoreError("Project history blob contains invalid JSON.") from exc

        state = empty_state()
        for key in state:
            if isinstance(data.get(key), dict):
                state[key] = data[key]
        return state

    def _save_sync(self, state: dict[str, dict[str, Any]]) -> None:
        payload = json.dumps(state, indent=2, sort_keys=True, default=str).encode("utf-8")
        try:
            from azure.storage.blob import ContentSettings

            self._client().upload_blob(
                payload,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/json"),
            )
        except Exception as exc:
            logger.error("Failed to save project history to Azure Blob", extra={"error": str(exc)})
            raise ProjectHistoryStoreError("Could not save project history.") from exc

    async def load(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            state = await asyncio.to_thread(self._load_sync)
            return deepcopy(state)

    async def save(self, state: dict[str, dict[str, Any]]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_sync, deepcopy(state))


project_history_store = AzureBlobProjectHistoryStore()
