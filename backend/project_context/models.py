from typing import Any, TypedDict


class ContextMessage(TypedDict):
    id: str
    role: str
    content: str
    agent_name: str | None
    metadata_json: dict[str, Any]
    created_at: str


class ProjectContext(TypedDict):
    project: dict[str, Any]
    workspace: dict[str, Any]
    conversation: dict[str, Any]
    recent_messages: list[ContextMessage]
    relevant_messages: list[ContextMessage]
    summary: str
    file_tree: list[dict[str, Any]]
    known_limitations: list[str]
    next_recommended_actions: list[str]
