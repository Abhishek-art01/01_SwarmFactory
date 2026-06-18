import re
from typing import Any

from core.config import settings
from project_context.models import ContextMessage, ProjectContext
from project_files.service import ProjectFileService
from project_history.service import (
    ForbiddenError,
    ProjectHistoryService,
    _assert_owned,
    project_history_service,
)

SECRET_PATTERNS = [
    re.compile(r"(AccountKey=)[^;\s]+", re.IGNORECASE),
    re.compile(r"((?:api[_-]?key|secret[_-]?key|token|password)\s*[:=]\s*)[^\s,;]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
]

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"user_id"} and not key.lower().endswith("connection_string")
    }


def _redact_content(content: str, max_chars: int) -> str:
    redacted = content
    if ".env" in redacted.lower():
        redacted = redacted.replace(".env", "[redacted-env-file]")
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    if len(redacted) > max_chars:
        return f"{redacted[:max_chars].rstrip()}..."
    return redacted


def _message_terms(content: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_]{3,}", content.lower())
        if token not in STOP_WORDS
    }


def _context_message(message: dict[str, Any], max_chars: int) -> ContextMessage:
    metadata = message.get("metadata_json")
    return {
        "id": message.get("id", ""),
        "role": message.get("role", ""),
        "content": _redact_content(message.get("content", ""), max_chars),
        "agent_name": message.get("agent_name"),
        "metadata_json": metadata if isinstance(metadata, dict) else {},
        "created_at": message.get("created_at", ""),
    }


class ProjectContextBuilder:
    def __init__(
        self,
        history_service: ProjectHistoryService = project_history_service,
        file_service: ProjectFileService | None = None,
    ) -> None:
        self.history_service = history_service
        self.file_service = file_service or ProjectFileService(history_service)

    async def build_project_context(
        self,
        project_id: str,
        conversation_id: str,
        user_id: str,
        max_recent_messages: int | None = None,
        max_relevant_messages: int | None = None,
        max_chars: int | None = None,
    ) -> ProjectContext:
        recent_limit = max(1, max_recent_messages or settings.PROJECT_CONTEXT_RECENT_MESSAGE_LIMIT)
        relevant_limit = max(0, max_relevant_messages if max_relevant_messages is not None else settings.PROJECT_CONTEXT_RELEVANT_MESSAGE_LIMIT)
        char_limit = max(1000, max_chars or settings.PROJECT_CONTEXT_MAX_CHARS)

        state = await self.history_service.store.load()
        project = _assert_owned(state["projects"].get(project_id), user_id, "project")
        conversation = _assert_owned(state["conversations"].get(conversation_id), user_id, "conversation")
        if conversation.get("project_id") != project_id:
            raise ForbiddenError("conversation does not belong to project")
        workspace = _assert_owned(state["workspaces"].get(conversation["workspace_id"]), user_id, "workspace")
        if workspace.get("project_id") != project_id:
            raise ForbiddenError("workspace does not belong to project")

        all_messages = sorted(
            [
                message
                for message in state["messages"].values()
                if message.get("conversation_id") == conversation_id and message.get("user_id") == user_id
            ],
            key=lambda message: message.get("created_at", ""),
        )

        per_message_limit = max(300, char_limit // max(recent_limit + relevant_limit + 1, 1))
        recent_raw = all_messages[-recent_limit:]
        recent_ids = {message.get("id") for message in recent_raw}
        relevant_raw = self._select_relevant_messages(
            messages=[message for message in all_messages if message.get("id") not in recent_ids],
            recent_messages=recent_raw,
            limit=relevant_limit,
        )
        known_limitations = [
            "Conversation summaries are currently lightweight placeholders.",
            "Real code editing and file-change memory are not enabled yet.",
        ]
        try:
            file_tree = await self.file_service.context_file_tree(user_id, project_id, workspace["id"])
        except Exception:
            file_tree = []
            known_limitations.append("Workspace file tree could not be loaded for this context.")
        pending_changes = [
            {
                "id": change.get("id", ""),
                "file_path": change.get("file_path", ""),
                "change_type": change.get("change_type", ""),
                "status": change.get("status", ""),
                "created_at": change.get("created_at", ""),
            }
            for change in sorted(
                [
                    change
                    for change in state.get("file_changes", {}).values()
                    if change.get("project_id") == project_id
                    and change.get("workspace_id") == workspace["id"]
                    and change.get("user_id") == user_id
                    and change.get("status") == "pending"
                ],
                key=lambda item: item.get("created_at", ""),
                reverse=True,
            )[:10]
        ]

        return {
            "project": _sanitize_record(project),
            "workspace": _sanitize_record(workspace),
            "conversation": _sanitize_record(conversation),
            "recent_messages": [_context_message(message, per_message_limit) for message in recent_raw],
            "relevant_messages": [_context_message(message, per_message_limit) for message in relevant_raw],
            "summary": self._summary(project, conversation, all_messages),
            "file_tree": file_tree,
            "pending_changes": pending_changes,
            "known_limitations": known_limitations,
            "next_recommended_actions": [
                "Use this context object when wiring the real coding-agent execution flow.",
                "Add project file indexing before allowing automated edits.",
                "Replace placeholder summaries with durable conversation summaries as history grows.",
            ],
        }

    def _select_relevant_messages(
        self,
        messages: list[dict[str, Any]],
        recent_messages: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or not messages:
            return []

        latest_user_message = next(
            (message for message in reversed(recent_messages) if message.get("role") == "user"),
            None,
        )
        query_terms = _message_terms(latest_user_message.get("content", "")) if latest_user_message else set()
        if not query_terms:
            return messages[-limit:]

        scored: list[tuple[int, str, dict[str, Any]]] = []
        for message in messages:
            terms = _message_terms(message.get("content", ""))
            score = len(query_terms.intersection(terms))
            if score:
                scored.append((score, message.get("created_at", ""), message))

        if not scored:
            return []

        return [
            message
            for _, _, message in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)[:limit]
        ]

    def _summary(
        self,
        project: dict[str, Any],
        conversation: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> str:
        project_name = project.get("name") or "Untitled project"
        title = conversation.get("title") or "New conversation"
        return (
            f'Project "{project_name}" conversation "{title}" has '
            f"{len(messages)} saved message(s). Full long-term summarization is not enabled yet."
        )


project_context_builder = ProjectContextBuilder()
