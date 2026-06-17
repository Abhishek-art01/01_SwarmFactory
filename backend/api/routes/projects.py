import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from project_context import project_context_builder
from project_files.service import FileTooLargeError, InvalidFilePathError, project_file_service
from project_history.service import (
    ForbiddenError,
    NotFoundError,
    current_user_id,
    project_history_service,
)
from project_history.store import ProjectHistoryStoreError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Projects"])

MessageRole = Literal["user", "assistant", "system", "agent"]


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ConversationCreateRequest(BaseModel):
    workspace_id: str | None = None
    title: str = Field(default="New conversation", max_length=160)


class ConversationTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)


class MessageCreateRequest(BaseModel):
    role: MessageRole = "user"
    content: str = Field(..., min_length=1, max_length=12000)
    agent_name: str | None = Field(default=None, max_length=80)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class FileContentRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., max_length=300000)


def _handle_history_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidFilePathError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_file_path", "message": str(exc)})
    if isinstance(exc, FileTooLargeError):
        return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail={"error": "file_too_large", "message": str(exc)})
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found", "message": str(exc)})
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "forbidden", "message": str(exc)})
    if isinstance(exc, ProjectHistoryStoreError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "history_store_unavailable", "message": str(exc)},
        )
    logger.error("Project history request failed", extra={"error": str(exc)})
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": "history_error", "message": "Project history request failed."},
    )


def _assistant_ack(
    user_message: str,
    context: dict[str, Any] | None = None,
    context_error: str | None = None,
) -> str:
    short = " ".join(user_message.split())[:140]
    if context_error:
        return (
            "I saved this instruction in the project conversation history, but project context could not be loaded yet. "
            "Real code-editing execution is still not connected.\n\n"
            f"Instruction: {short}"
        )

    if context:
        recent_count = len(context.get("recent_messages", []))
        relevant_count = len(context.get("relevant_messages", []))
        return (
            "Saved your instruction. I loaded recent project context for this conversation, and this will be used "
            "for future code-editing memory. Real code editing is not connected yet.\n\n"
            f"Context loaded: {recent_count} recent message(s), {relevant_count} relevant prior message(s).\n"
            f"Instruction: {short}"
        )

    return (
        "I saved this instruction in the project conversation history. "
        "Code-editing execution will be connected in a later feature step.\n\n"
        f"Instruction: {short}"
    )


@router.get("/projects")
async def list_projects() -> list[dict[str, Any]]:
    try:
        return await project_history_service.list_projects(current_user_id())
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreateRequest) -> dict[str, Any]:
    try:
        return await project_history_service.create_project(
            user_id=current_user_id(),
            name=payload.name,
            description=payload.description,
        )
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    try:
        return await project_history_service.get_project(current_user_id(), project_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}/conversations")
async def list_conversations(project_id: str) -> list[dict[str, Any]]:
    try:
        return await project_history_service.list_conversations(current_user_id(), project_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.post("/projects/{project_id}/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(project_id: str, payload: ConversationCreateRequest) -> dict[str, Any]:
    try:
        return await project_history_service.create_conversation(
            user_id=current_user_id(),
            project_id=project_id,
            workspace_id=payload.workspace_id,
            title=payload.title,
        )
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}/conversations/latest")
async def latest_conversation(project_id: str) -> dict[str, Any] | None:
    try:
        return await project_history_service.latest_conversation(current_user_id(), project_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}/conversations/{conversation_id}/context")
async def get_project_context(project_id: str, conversation_id: str) -> dict[str, Any]:
    try:
        return await project_context_builder.build_project_context(
            project_id=project_id,
            conversation_id=conversation_id,
            user_id=current_user_id(),
        )
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}/workspaces/{workspace_id}/files")
async def list_workspace_files(project_id: str, workspace_id: str) -> list[dict[str, Any]]:
    try:
        return await project_file_service.list_files(current_user_id(), project_id, workspace_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}/workspaces/{workspace_id}/files/tree")
async def get_workspace_file_tree(project_id: str, workspace_id: str) -> dict[str, Any]:
    try:
        return await project_file_service.list_file_tree(current_user_id(), project_id, workspace_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/projects/{project_id}/workspaces/{workspace_id}/files/content")
async def get_workspace_file_content(
    project_id: str,
    workspace_id: str,
    path: str = Query(..., min_length=1, max_length=500),
) -> dict[str, Any]:
    try:
        return await project_file_service.read_file(current_user_id(), project_id, workspace_id, path)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.post("/projects/{project_id}/workspaces/{workspace_id}/files", status_code=status.HTTP_201_CREATED)
async def create_workspace_file(project_id: str, workspace_id: str, payload: FileContentRequest) -> dict[str, Any]:
    try:
        return await project_file_service.upsert_file(
            current_user_id(),
            project_id,
            workspace_id,
            payload.path,
            payload.content,
        )
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.put("/projects/{project_id}/workspaces/{workspace_id}/files/content")
async def update_workspace_file_content(project_id: str, workspace_id: str, payload: FileContentRequest) -> dict[str, Any]:
    try:
        return await project_file_service.upsert_file(
            current_user_id(),
            project_id,
            workspace_id,
            payload.path,
            payload.content,
        )
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    try:
        return await project_history_service.get_messages(current_user_id(), conversation_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def create_message(conversation_id: str, payload: MessageCreateRequest) -> dict[str, Any]:
    try:
        user_id = current_user_id()
        message = await project_history_service.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role=payload.role,
            content=payload.content,
            agent_name=payload.agent_name,
            metadata_json=payload.metadata_json,
        )

        response: dict[str, Any] = {"message": message}
        if payload.role == "user":
            context = None
            context_error = None
            try:
                context = await project_context_builder.build_project_context(
                    project_id=message["project_id"],
                    conversation_id=conversation_id,
                    user_id=user_id,
                )
            except Exception as exc:
                context_error = str(exc)
                logger.warning("Project context could not be loaded", extra={"error": context_error})

            assistant_message = await project_history_service.add_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=_assistant_ack(payload.content, context=context, context_error=context_error),
                agent_name="Swarm Factory",
                metadata_json={
                    "status": "context_loaded" if context else "context_unavailable",
                    "instruction_mode": "project_context",
                    "context_recent_messages": len(context.get("recent_messages", [])) if context else 0,
                    "context_relevant_messages": len(context.get("relevant_messages", [])) if context else 0,
                    "error": context_error,
                },
            )
            response["assistant_message"] = assistant_message
        return response
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, payload: ConversationTitleRequest) -> dict[str, Any]:
    try:
        return await project_history_service.update_conversation_title(current_user_id(), conversation_id, payload.title)
    except Exception as exc:
        raise _handle_history_error(exc) from exc


@router.delete("/conversations/{conversation_id}")
async def archive_conversation(conversation_id: str) -> dict[str, Any]:
    try:
        return await project_history_service.archive_conversation(current_user_id(), conversation_id)
    except Exception as exc:
        raise _handle_history_error(exc) from exc
