import difflib
import hashlib
import uuid
from typing import Any

from core.config import settings
from project_changes.models import FileChangeProposal
from project_files.service import (
    FileTooLargeError,
    ProjectFileService,
    infer_language,
    normalize_file_path,
    project_file_service,
    redact_content,
)
from project_history.service import ForbiddenError, NotFoundError
from project_history.store import utc_now


EMPTY_CONTENT_HASH = hashlib.sha256(b"").hexdigest()


class ProjectChangeError(RuntimeError):
    pass


class InvalidChangeStatusError(ProjectChangeError):
    pass


class ChangeConflictError(ProjectChangeError):
    pass


class UnsupportedChangeTypeError(ProjectChangeError):
    pass


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _limit(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}\n...[truncated]"


def _public_change(change: dict[str, Any]) -> FileChangeProposal:
    return {
        "id": change.get("id", ""),
        "project_id": change.get("project_id", ""),
        "workspace_id": change.get("workspace_id", ""),
        "user_id": change.get("user_id", ""),
        "file_path": change.get("file_path", ""),
        "path": change.get("file_path", ""),
        "change_type": change.get("change_type", "update"),
        "status": change.get("status", "pending"),
        "old_content_hash": change.get("old_content_hash", ""),
        "new_content_hash": change.get("new_content_hash", ""),
        "old_content_preview": change.get("old_content_preview", ""),
        "new_content_preview": change.get("new_content_preview", ""),
        "diff": change.get("diff", ""),
        "created_by": change.get("created_by", "manual"),
        "agent_run_id": change.get("agent_run_id"),
        "conversation_id": change.get("conversation_id"),
        "message_id": change.get("message_id"),
        "created_at": change.get("created_at", ""),
        "updated_at": change.get("updated_at", ""),
        "approved_at": change.get("approved_at"),
        "rejected_at": change.get("rejected_at"),
        "applied_at": change.get("applied_at"),
    }


class ProjectChangeService:
    def __init__(self, file_service: ProjectFileService = project_file_service) -> None:
        self.file_service = file_service
        self.history_service = file_service.history_service

    async def create_change_proposal(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        path: str,
        proposed_content: str,
        change_type: str = "update",
        conversation_id: str | None = None,
        message_id: str | None = None,
        created_by: str = "manual",
    ) -> FileChangeProposal:
        if change_type not in {"create", "update"}:
            raise UnsupportedChangeTypeError("only create and update file changes are supported")
        if len(proposed_content) > settings.PROJECT_CHANGES_MAX_PROPOSED_CONTENT_CHARS:
            raise FileTooLargeError("proposed content exceeds the configured size limit")
        if len(proposed_content.encode("utf-8")) > settings.PROJECT_FILES_MAX_FILE_SIZE:
            raise FileTooLargeError("file content exceeds the configured size limit")

        safe_path = normalize_file_path(path)
        state = await self.history_service.store.load()
        self.file_service._validate_workspace(state, user_id, project_id, workspace_id)
        state.setdefault("file_changes", {})
        file = self._find_file(state, user_id, project_id, workspace_id, safe_path)

        if change_type == "update":
            if not file:
                raise NotFoundError("file not found")
            old_content = await self.file_service.content_store.read_text(file["content_blob_name"])
        else:
            if file:
                raise InvalidChangeStatusError("create proposal cannot target an existing file")
            old_content = ""

        diff = self.generate_diff(safe_path, old_content, proposed_content)
        old_preview, _ = redact_content(old_content)
        new_preview, _ = redact_content(proposed_content)
        now = utc_now()
        change_id = str(uuid.uuid4())
        change = {
            "id": change_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "file_path": safe_path,
            "change_type": change_type,
            "status": "pending",
            "old_content_hash": _sha256(old_content),
            "new_content_hash": _sha256(proposed_content),
            "old_content_preview": _limit(old_preview, settings.PROJECT_FILES_MAX_PREVIEW_CHARS),
            "new_content_preview": _limit(new_preview, settings.PROJECT_FILES_MAX_PREVIEW_CHARS),
            "proposed_content": proposed_content,
            "diff": diff,
            "created_by": created_by[:80] or "manual",
            "agent_run_id": None,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "created_at": now,
            "updated_at": now,
            "approved_at": None,
            "rejected_at": None,
            "applied_at": None,
        }
        state["file_changes"][change_id] = change
        state["projects"][project_id]["updated_at"] = now
        state["workspaces"][workspace_id]["updated_at"] = now
        await self.history_service.store.save(state)
        return _public_change(change)

    async def list_change_proposals(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[FileChangeProposal]:
        state = await self.history_service.store.load()
        self.file_service._validate_workspace(state, user_id, project_id, workspace_id)
        state.setdefault("file_changes", {})
        changes = [
            change
            for change in state["file_changes"].values()
            if change.get("user_id") == user_id
            and change.get("project_id") == project_id
            and change.get("workspace_id") == workspace_id
            and (status is None or change.get("status") == status)
        ]
        return [_public_change(change) for change in sorted(changes, key=lambda item: item.get("created_at", ""), reverse=True)]

    async def get_change_proposal(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        change_id: str,
    ) -> FileChangeProposal:
        state = await self.history_service.store.load()
        change = self._get_owned_change(state, user_id, project_id, workspace_id, change_id)
        return _public_change(change)

    async def approve_change(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        change_id: str,
    ) -> FileChangeProposal:
        state = await self.history_service.store.load()
        change = self._get_owned_change(state, user_id, project_id, workspace_id, change_id)
        if change.get("status") != "pending":
            raise InvalidChangeStatusError("only pending changes can be approved")

        safe_path = normalize_file_path(change.get("file_path", ""))
        file = self._find_file(state, user_id, project_id, workspace_id, safe_path)
        if change.get("change_type") == "create":
            current_hash = EMPTY_CONTENT_HASH if not file else file.get("hash", "")
        else:
            if not file:
                raise ChangeConflictError("target file no longer exists")
            current_hash = file.get("hash", "")

        if current_hash != change.get("old_content_hash"):
            raise ChangeConflictError("file content changed after this proposal was created")

        now = utc_now()
        proposed_content = change.get("proposed_content", "")
        size = len(proposed_content.encode("utf-8"))
        if size > settings.PROJECT_FILES_MAX_FILE_SIZE:
            raise FileTooLargeError("file content exceeds the configured size limit")

        file_id = file["id"] if file else str(uuid.uuid4())
        blob_name = self.file_service._blob_name(workspace_id, safe_path)
        await self.file_service.content_store.write_text(blob_name, proposed_content)
        state.setdefault("files", {})
        state["files"][file_id] = {
            "id": file_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "path": safe_path,
            "name": safe_path.split("/")[-1],
            "language": infer_language(safe_path),
            "size": size,
            "hash": _sha256(proposed_content),
            "content_blob_name": blob_name,
            "created_at": file.get("created_at", now) if file else now,
            "updated_at": now,
        }
        change["status"] = "applied"
        change["approved_at"] = now
        change["applied_at"] = now
        change["updated_at"] = now
        state["projects"][project_id]["updated_at"] = now
        state["workspaces"][workspace_id]["updated_at"] = now
        await self.history_service.store.save(state)
        return _public_change(change)

    async def reject_change(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str,
        change_id: str,
    ) -> FileChangeProposal:
        state = await self.history_service.store.load()
        change = self._get_owned_change(state, user_id, project_id, workspace_id, change_id)
        if change.get("status") != "pending":
            raise InvalidChangeStatusError("only pending changes can be rejected")
        now = utc_now()
        change["status"] = "rejected"
        change["rejected_at"] = now
        change["updated_at"] = now
        await self.history_service.store.save(state)
        return _public_change(change)

    def generate_diff(self, path: str, old_content: str, proposed_content: str) -> str:
        old_redacted, _ = redact_content(old_content)
        new_redacted, _ = redact_content(proposed_content)
        diff_lines = list(
            difflib.unified_diff(
                old_redacted.splitlines(),
                new_redacted.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        diff = "\n".join(diff_lines)
        if diff:
            diff = f"{diff}\n"
        return _limit(diff, settings.PROJECT_CHANGES_MAX_DIFF_CHARS)

    def _get_owned_change(
        self,
        state: dict[str, dict[str, Any]],
        user_id: str,
        project_id: str,
        workspace_id: str,
        change_id: str,
    ) -> dict[str, Any]:
        self.file_service._validate_workspace(state, user_id, project_id, workspace_id)
        state.setdefault("file_changes", {})
        change = state["file_changes"].get(change_id)
        if not change:
            raise NotFoundError("file change not found")
        if change.get("user_id") != user_id:
            raise ForbiddenError("file change is not accessible")
        if change.get("project_id") != project_id or change.get("workspace_id") != workspace_id:
            raise ForbiddenError("file change does not belong to workspace")
        return change

    def _find_file(
        self,
        state: dict[str, dict[str, Any]],
        user_id: str,
        project_id: str,
        workspace_id: str,
        path: str,
    ) -> dict[str, Any] | None:
        state.setdefault("files", {})
        return next(
            (
                file
                for file in state["files"].values()
                if file.get("workspace_id") == workspace_id
                and file.get("project_id") == project_id
                and file.get("user_id") == user_id
                and file.get("path") == path
            ),
            None,
        )


project_change_service = ProjectChangeService()
