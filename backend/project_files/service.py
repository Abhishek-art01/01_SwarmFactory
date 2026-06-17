import asyncio
import hashlib
import logging
import posixpath
import re
import uuid
from typing import Any, Protocol

from core.config import settings
from project_files.models import FileContentResponse, FileMetadata, FileTreeNode, FileTreeResponse
from project_history.service import (
    ForbiddenError,
    NotFoundError,
    ProjectHistoryService,
    _assert_owned,
    project_history_service,
)
from project_history.store import ProjectHistoryStoreError, utc_now

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    re.compile(r"(AccountKey=)[^;\s]+", re.IGNORECASE),
    re.compile(r"((?:api[_-]?key|secret[_-]?key|token|password)\s*[:=]\s*)[^\s,;]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
]

SECRET_FILE_NAMES = {".env", ".env.local", ".env.production", ".env.staging", ".npmrc", ".pypirc"}


class InvalidFilePathError(RuntimeError):
    pass


class FileTooLargeError(RuntimeError):
    pass


class FileContentStore(Protocol):
    async def write_text(self, blob_name: str, content: str) -> None:
        ...

    async def read_text(self, blob_name: str) -> str:
        ...


class AzureBlobFileContentStore:
    def __init__(
        self,
        connection_string: str | None = None,
        container_name: str | None = None,
    ) -> None:
        self.connection_string = connection_string if connection_string is not None else settings.AZURE_STORAGE_CONNECTION_STRING
        self.container_name = container_name or settings.AZURE_STORAGE_CONTAINER
        self._container_client: Any = None

    def _container(self) -> Any:
        if not self.connection_string:
            raise ProjectHistoryStoreError("AZURE_STORAGE_CONNECTION_STRING is required for workspace file storage.")

        if self._container_client is None:
            try:
                from azure.storage.blob import BlobServiceClient
            except ImportError as exc:
                raise ProjectHistoryStoreError("azure-storage-blob is required for workspace file storage.") from exc

            service = BlobServiceClient.from_connection_string(self.connection_string)
            container = service.get_container_client(self.container_name)
            try:
                container.create_container()
            except Exception:
                pass
            self._container_client = container
        return self._container_client

    def _write_sync(self, blob_name: str, content: str) -> None:
        try:
            from azure.storage.blob import ContentSettings

            self._container().get_blob_client(blob_name).upload_blob(
                content.encode("utf-8"),
                overwrite=True,
                content_settings=ContentSettings(content_type="text/plain; charset=utf-8"),
            )
        except Exception as exc:
            logger.error("Failed to save workspace file content to Azure Blob", extra={"error": str(exc)})
            raise ProjectHistoryStoreError("Could not save workspace file content.") from exc

    def _read_sync(self, blob_name: str) -> str:
        try:
            raw = self._container().get_blob_client(blob_name).download_blob().readall()
        except Exception as exc:
            if exc.__class__.__name__ == "ResourceNotFoundError":
                raise NotFoundError("file content not found") from exc
            logger.error("Failed to load workspace file content from Azure Blob", extra={"error": str(exc)})
            raise ProjectHistoryStoreError("Could not load workspace file content.") from exc
        return raw.decode("utf-8", errors="replace")

    async def write_text(self, blob_name: str, content: str) -> None:
        await asyncio.to_thread(self._write_sync, blob_name, content)

    async def read_text(self, blob_name: str) -> str:
        return await asyncio.to_thread(self._read_sync, blob_name)


def normalize_file_path(path: str) -> str:
    raw = path.strip().replace("\\", "/")
    if not raw:
        raise InvalidFilePathError("file path is required")
    if raw.startswith("/"):
        raise InvalidFilePathError("absolute file paths are not allowed")

    normalized = posixpath.normpath(raw)
    if normalized in {"", "."}:
        raise InvalidFilePathError("file path is required")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InvalidFilePathError("path traversal is not allowed")

    name = parts[-1].lower()
    if name in SECRET_FILE_NAMES or name.startswith(".env"):
        raise InvalidFilePathError("secret-like files are not allowed")
    return normalized


def infer_language(path: str) -> str:
    extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "py": "python",
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "json": "json",
        "md": "markdown",
        "txt": "text",
        "css": "css",
        "html": "html",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(extension, extension or "plaintext")


def redact_content(content: str) -> tuple[str, bool]:
    redacted = content
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted, redacted != content


def public_file_metadata(file: dict[str, Any]) -> FileMetadata:
    return {
        "id": file.get("id", ""),
        "project_id": file.get("project_id", ""),
        "workspace_id": file.get("workspace_id", ""),
        "user_id": file.get("user_id", ""),
        "path": file.get("path", ""),
        "name": file.get("name", ""),
        "language": file.get("language", "plaintext"),
        "size": int(file.get("size", 0)),
        "hash": file.get("hash", ""),
        "content_blob_name": file.get("content_blob_name", ""),
        "created_at": file.get("created_at", ""),
        "updated_at": file.get("updated_at", ""),
    }


def context_file_metadata(file: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": file.get("path", ""),
        "name": file.get("name", ""),
        "type": "file",
        "language": file.get("language", "plaintext"),
        "size": int(file.get("size", 0)),
        "hash": file.get("hash", ""),
        "updated_at": file.get("updated_at", ""),
    }


def build_tree(files: list[dict[str, Any]]) -> list[FileTreeNode]:
    root: dict[str, Any] = {}

    for file in sorted(files, key=lambda item: item.get("path", "")):
        parts = file["path"].split("/")
        cursor = root
        current_path = ""
        for part in parts[:-1]:
            current_path = f"{current_path}/{part}" if current_path else part
            cursor = cursor.setdefault(
                part,
                {"name": part, "path": current_path, "type": "directory", "children": {}},
            )["children"]

        name = parts[-1]
        cursor[name] = {
            "name": name,
            "path": file["path"],
            "type": "file",
            "language": file.get("language", "plaintext"),
            "size": int(file.get("size", 0)),
            "hash": file.get("hash", ""),
            "updated_at": file.get("updated_at", ""),
        }

    def materialize(nodes: dict[str, Any]) -> list[FileTreeNode]:
        result = []
        for node in sorted(nodes.values(), key=lambda item: (item["type"] == "file", item["name"].lower())):
            if node["type"] == "directory":
                result.append({**node, "children": materialize(node["children"])})
            else:
                result.append(node)
        return result

    return materialize(root)


class ProjectFileService:
    def __init__(
        self,
        history_service: ProjectHistoryService = project_history_service,
        content_store: FileContentStore | None = None,
    ) -> None:
        self.history_service = history_service
        self.content_store = content_store or AzureBlobFileContentStore()

    async def list_files(self, user_id: str, project_id: str, workspace_id: str) -> list[FileMetadata]:
        state = await self.history_service.store.load()
        self._validate_workspace(state, user_id, project_id, workspace_id)
        files = self._workspace_files(state, user_id, project_id, workspace_id)
        return [public_file_metadata(file) for file in files]

    async def list_file_tree(self, user_id: str, project_id: str, workspace_id: str) -> FileTreeResponse:
        files = await self.list_files(user_id, project_id, workspace_id)
        return {"workspace_id": workspace_id, "files": files, "tree": build_tree(files)}

    async def context_file_tree(self, user_id: str, project_id: str, workspace_id: str) -> list[dict[str, Any]]:
        state = await self.history_service.store.load()
        self._validate_workspace(state, user_id, project_id, workspace_id)
        return [
            context_file_metadata(file)
            for file in self._workspace_files(state, user_id, project_id, workspace_id)
        ]

    async def upsert_file(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        path: str,
        content: str,
    ) -> FileMetadata:
        safe_path = normalize_file_path(path)
        size = len(content.encode("utf-8"))
        if size > settings.PROJECT_FILES_MAX_FILE_SIZE:
            raise FileTooLargeError("file content exceeds the configured size limit")

        state = await self.history_service.store.load()
        self._validate_workspace(state, user_id, project_id, workspace_id)
        state.setdefault("files", {})

        existing = next(
            (
                file
                for file in state["files"].values()
                if file.get("workspace_id") == workspace_id
                and file.get("project_id") == project_id
                and file.get("user_id") == user_id
                and file.get("path") == safe_path
            ),
            None,
        )
        now = utc_now()
        file_id = existing["id"] if existing else str(uuid.uuid4())
        blob_name = self._blob_name(workspace_id, safe_path)
        await self.content_store.write_text(blob_name, content)

        file = {
            "id": file_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "path": safe_path,
            "name": safe_path.split("/")[-1],
            "language": infer_language(safe_path),
            "size": size,
            "hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content_blob_name": blob_name,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        state["files"][file_id] = file
        state["projects"][project_id]["updated_at"] = now
        state["workspaces"][workspace_id]["updated_at"] = now
        await self.history_service.store.save(state)
        return public_file_metadata(file)

    async def read_file(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        path: str,
    ) -> FileContentResponse:
        safe_path = normalize_file_path(path)
        state = await self.history_service.store.load()
        self._validate_workspace(state, user_id, project_id, workspace_id)
        file = next(
            (
                item
                for item in state.get("files", {}).values()
                if item.get("workspace_id") == workspace_id
                and item.get("project_id") == project_id
                and item.get("user_id") == user_id
                and item.get("path") == safe_path
            ),
            None,
        )
        if not file:
            raise NotFoundError("file not found")

        content = await self.content_store.read_text(file["content_blob_name"])
        redacted_content, redacted = redact_content(content)
        limit = settings.PROJECT_FILES_MAX_PREVIEW_CHARS
        truncated = len(redacted_content) > limit
        if truncated:
            redacted_content = redacted_content[:limit]
        return {
            "file": public_file_metadata(file),
            "content": redacted_content,
            "truncated": truncated,
            "redacted": redacted,
        }

    def _blob_name(self, workspace_id: str, path: str) -> str:
        prefix = settings.PROJECT_FILES_BLOB_PREFIX.strip("/")
        return f"{prefix}/{workspace_id}/{path}"

    def _validate_workspace(
        self,
        state: dict[str, dict[str, Any]],
        user_id: str,
        project_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        state.setdefault("files", {})
        _assert_owned(state["projects"].get(project_id), user_id, "project")
        workspace = _assert_owned(state["workspaces"].get(workspace_id), user_id, "workspace")
        if workspace.get("project_id") != project_id:
            raise ForbiddenError("workspace does not belong to project")
        return workspace

    def _workspace_files(
        self,
        state: dict[str, dict[str, Any]],
        user_id: str,
        project_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        return sorted(
            [
                file
                for file in state.get("files", {}).values()
                if file.get("workspace_id") == workspace_id
                and file.get("project_id") == project_id
                and file.get("user_id") == user_id
            ],
            key=lambda file: file.get("path", ""),
        )


project_file_service = ProjectFileService()
