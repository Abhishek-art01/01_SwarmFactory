from typing import Any, Literal, TypedDict


ChangeType = Literal["create", "update", "delete"]
ChangeStatus = Literal["pending", "approved", "rejected", "applied", "failed"]


class FileChangeProposal(TypedDict, total=False):
    id: str
    project_id: str
    workspace_id: str
    user_id: str
    file_path: str
    path: str
    change_type: ChangeType
    status: ChangeStatus
    old_content_hash: str
    new_content_hash: str
    old_content_preview: str
    new_content_preview: str
    proposed_content: str
    diff: str
    created_by: str
    agent_run_id: str | None
    conversation_id: str | None
    message_id: str | None
    created_at: str
    updated_at: str
    approved_at: str | None
    rejected_at: str | None
    applied_at: str | None


State = dict[str, dict[str, Any]]
