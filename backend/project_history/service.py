import uuid
from typing import Any, Literal

from project_history.store import project_history_store, utc_now

MessageRole = Literal["user", "assistant", "system", "agent"]


class ProjectHistoryError(RuntimeError):
    pass


class NotFoundError(ProjectHistoryError):
    pass


class ForbiddenError(ProjectHistoryError):
    pass


def current_user_id() -> str:
    from core.config import settings

    return settings.DEFAULT_USER_ID


def _new_id() -> str:
    return str(uuid.uuid4())


def _assert_owned(record: dict[str, Any] | None, user_id: str, name: str) -> dict[str, Any]:
    if not record:
        raise NotFoundError(f"{name} not found")
    if record.get("user_id") != user_id:
        raise ForbiddenError(f"{name} is not accessible")
    return record


def _conversation_title(content: str) -> str:
    cleaned = " ".join(content.strip().split())
    if not cleaned:
        return "New conversation"
    return cleaned[:60]


class ProjectHistoryService:
    def __init__(self, store=project_history_store) -> None:
        self.store = store

    async def list_projects(self, user_id: str) -> list[dict[str, Any]]:
        state = await self.store.load()
        projects = [p for p in state["projects"].values() if p.get("user_id") == user_id]
        return sorted(projects, key=lambda p: p.get("updated_at", ""), reverse=True)

    async def create_project(self, user_id: str, name: str, description: str = "") -> dict[str, Any]:
        state = await self.store.load()
        now = utc_now()
        project_id = _new_id()
        workspace_id = _new_id()
        project = {
            "id": project_id,
            "user_id": user_id,
            "name": name.strip(),
            "description": description.strip(),
            "created_at": now,
            "updated_at": now,
        }
        workspace = {
            "id": workspace_id,
            "project_id": project_id,
            "user_id": user_id,
            "name": "Default workspace",
            "storage_key": f"workspaces/{user_id}/{project_id}/{workspace_id}",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        state["projects"][project_id] = project
        state["workspaces"][workspace_id] = workspace
        await self.store.save(state)
        return {**project, "default_workspace_id": workspace_id}

    async def get_project(self, user_id: str, project_id: str) -> dict[str, Any]:
        state = await self.store.load()
        project = _assert_owned(state["projects"].get(project_id), user_id, "project")
        workspaces = [
            w for w in state["workspaces"].values()
            if w.get("project_id") == project_id and w.get("user_id") == user_id
        ]
        return {**project, "workspaces": sorted(workspaces, key=lambda w: w.get("created_at", ""))}

    async def list_conversations(self, user_id: str, project_id: str) -> list[dict[str, Any]]:
        state = await self.store.load()
        _assert_owned(state["projects"].get(project_id), user_id, "project")
        conversations = [
            c for c in state["conversations"].values()
            if c.get("project_id") == project_id and c.get("user_id") == user_id and not c.get("archived")
        ]
        return sorted(conversations, key=lambda c: c.get("updated_at", ""), reverse=True)

    async def create_conversation(
        self,
        user_id: str,
        project_id: str,
        workspace_id: str | None = None,
        title: str = "New conversation",
    ) -> dict[str, Any]:
        state = await self.store.load()
        _assert_owned(state["projects"].get(project_id), user_id, "project")
        if workspace_id:
            workspace = _assert_owned(state["workspaces"].get(workspace_id), user_id, "workspace")
            if workspace.get("project_id") != project_id:
                raise ForbiddenError("workspace does not belong to project")
        else:
            workspace = next(
                (
                    w for w in state["workspaces"].values()
                    if w.get("project_id") == project_id and w.get("user_id") == user_id
                ),
                None,
            )
            if not workspace:
                raise NotFoundError("workspace not found")
            workspace_id = workspace["id"]

        now = utc_now()
        conversation = {
            "id": _new_id(),
            "project_id": project_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "title": title.strip() or "New conversation",
            "created_at": now,
            "updated_at": now,
            "archived": False,
        }
        state["conversations"][conversation["id"]] = conversation
        state["projects"][project_id]["updated_at"] = now
        await self.store.save(state)
        return conversation

    async def latest_conversation(self, user_id: str, project_id: str) -> dict[str, Any] | None:
        conversations = await self.list_conversations(user_id, project_id)
        return conversations[0] if conversations else None

    async def get_messages(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        state = await self.store.load()
        conversation = _assert_owned(state["conversations"].get(conversation_id), user_id, "conversation")
        messages = [
            m for m in state["messages"].values()
            if m.get("conversation_id") == conversation["id"] and m.get("user_id") == user_id
        ]
        return sorted(messages, key=lambda m: m.get("created_at", ""))

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: MessageRole,
        content: str,
        agent_name: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = await self.store.load()
        conversation = _assert_owned(state["conversations"].get(conversation_id), user_id, "conversation")
        project = _assert_owned(state["projects"].get(conversation["project_id"]), user_id, "project")
        _assert_owned(state["workspaces"].get(conversation["workspace_id"]), user_id, "workspace")

        now = utc_now()
        message = {
            "id": _new_id(),
            "conversation_id": conversation_id,
            "project_id": conversation["project_id"],
            "workspace_id": conversation["workspace_id"],
            "user_id": user_id,
            "role": role,
            "content": content.strip(),
            "agent_name": agent_name,
            "metadata_json": metadata_json or {},
            "created_at": now,
        }
        state["messages"][message["id"]] = message
        conversation["updated_at"] = now
        project["updated_at"] = now
        if role == "user" and conversation["title"] == "New conversation":
            conversation["title"] = _conversation_title(content)
        await self.store.save(state)
        return message

    async def update_conversation_title(self, user_id: str, conversation_id: str, title: str) -> dict[str, Any]:
        state = await self.store.load()
        conversation = _assert_owned(state["conversations"].get(conversation_id), user_id, "conversation")
        conversation["title"] = title.strip() or conversation["title"]
        conversation["updated_at"] = utc_now()
        await self.store.save(state)
        return conversation

    async def archive_conversation(self, user_id: str, conversation_id: str) -> dict[str, Any]:
        state = await self.store.load()
        conversation = _assert_owned(state["conversations"].get(conversation_id), user_id, "conversation")
        conversation["archived"] = True
        conversation["updated_at"] = utc_now()
        await self.store.save(state)
        return conversation


project_history_service = ProjectHistoryService()
