import pytest
from fastapi import HTTPException

from api.routes import projects
from project_context.builder import ProjectContextBuilder
from project_history.service import ForbiddenError, ProjectHistoryService
from project_history.store import empty_state


class FakeStore:
    def __init__(self):
        self.state = empty_state()

    async def load(self):
        return {
            "projects": dict(self.state["projects"]),
            "workspaces": dict(self.state["workspaces"]),
            "conversations": dict(self.state["conversations"]),
            "messages": dict(self.state["messages"]),
        }

    async def save(self, state):
        self.state = state


@pytest.mark.asyncio
async def test_context_builder_returns_project_workspace_and_conversation_metadata():
    service = ProjectHistoryService(FakeStore())
    builder = ProjectContextBuilder(service)

    project = await service.create_project("user-1", "Demo", "Context test")
    conversation = await service.create_conversation("user-1", project["id"], title="Planning")

    context = await builder.build_project_context(project["id"], conversation["id"], "user-1")

    assert context["project"]["id"] == project["id"]
    assert context["project"]["name"] == "Demo"
    assert context["workspace"]["project_id"] == project["id"]
    assert context["conversation"]["id"] == conversation["id"]
    assert "Full long-term summarization is not enabled yet" in context["summary"]


@pytest.mark.asyncio
async def test_context_builder_includes_recent_messages_and_limits_count():
    service = ProjectHistoryService(FakeStore())
    builder = ProjectContextBuilder(service)

    project = await service.create_project("user-1", "Demo")
    conversation = await service.create_conversation("user-1", project["id"])
    for index in range(6):
        await service.add_message("user-1", conversation["id"], "user", f"Message {index}")

    context = await builder.build_project_context(
        project["id"],
        conversation["id"],
        "user-1",
        max_recent_messages=3,
    )

    assert [message["content"] for message in context["recent_messages"]] == [
        "Message 3",
        "Message 4",
        "Message 5",
    ]


@pytest.mark.asyncio
async def test_context_builder_selects_relevant_previous_messages():
    service = ProjectHistoryService(FakeStore())
    builder = ProjectContextBuilder(service)

    project = await service.create_project("user-1", "Demo")
    conversation = await service.create_conversation("user-1", project["id"])
    await service.add_message("user-1", conversation["id"], "user", "Improve login validation errors")
    await service.add_message("user-1", conversation["id"], "assistant", "Saved login validation notes")
    await service.add_message("user-1", conversation["id"], "user", "Update dashboard chart colors")
    await service.add_message("user-1", conversation["id"], "user", "Fix login loading state")

    context = await builder.build_project_context(
        project["id"],
        conversation["id"],
        "user-1",
        max_recent_messages=1,
        max_relevant_messages=2,
    )

    relevant = " ".join(message["content"] for message in context["relevant_messages"])
    assert "login" in relevant
    assert "dashboard chart" not in relevant


@pytest.mark.asyncio
async def test_context_builder_rejects_wrong_project_conversation_relationship():
    service = ProjectHistoryService(FakeStore())
    builder = ProjectContextBuilder(service)

    first_project = await service.create_project("user-1", "First")
    second_project = await service.create_project("user-1", "Second")
    conversation = await service.create_conversation("user-1", first_project["id"])

    with pytest.raises(ForbiddenError):
        await builder.build_project_context(second_project["id"], conversation["id"], "user-1")


@pytest.mark.asyncio
async def test_context_endpoint_returns_builder_result(monkeypatch):
    expected = {
        "project": {"id": "project-1"},
        "workspace": {},
        "conversation": {"id": "conversation-1"},
        "recent_messages": [],
        "relevant_messages": [],
        "summary": "",
        "file_tree": [],
        "pending_changes": [],
        "known_limitations": [],
        "next_recommended_actions": [],
    }

    class FakeBuilder:
        async def build_project_context(self, project_id, conversation_id, user_id):
            assert project_id == "project-1"
            assert conversation_id == "conversation-1"
            assert user_id == "user-1"
            return expected

    monkeypatch.setattr(projects, "project_context_builder", FakeBuilder())
    monkeypatch.setattr(projects, "current_user_id", lambda: "user-1")

    assert await projects.get_project_context("project-1", "conversation-1") == expected


@pytest.mark.asyncio
async def test_context_endpoint_blocks_invalid_access(monkeypatch):
    class FakeBuilder:
        async def build_project_context(self, project_id, conversation_id, user_id):
            raise ForbiddenError("conversation is not accessible")

    monkeypatch.setattr(projects, "project_context_builder", FakeBuilder())
    monkeypatch.setattr(projects, "current_user_id", lambda: "user-1")

    with pytest.raises(HTTPException) as exc_info:
        await projects.get_project_context("project-1", "conversation-1")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_message_flow_saves_context_aware_assistant_message(monkeypatch):
    service = ProjectHistoryService(FakeStore())
    project = await service.create_project("user-1", "Demo")
    conversation = await service.create_conversation("user-1", project["id"])

    class FakeBuilder:
        async def build_project_context(self, project_id, conversation_id, user_id):
            return {
                "project": {"id": project_id},
                "workspace": {},
                "conversation": {"id": conversation_id},
                "recent_messages": [{"id": "m1"}],
                "relevant_messages": [],
                "summary": "",
                "file_tree": [],
                "pending_changes": [],
                "known_limitations": [],
                "next_recommended_actions": [],
            }

    monkeypatch.setattr(projects, "project_history_service", service)
    monkeypatch.setattr(projects, "project_context_builder", FakeBuilder())
    monkeypatch.setattr(projects, "current_user_id", lambda: "user-1")

    response = await projects.create_message(
        conversation["id"],
        projects.MessageCreateRequest(role="user", content="Fix the login page"),
    )
    messages = await service.get_messages("user-1", conversation["id"])

    assert response["message"]["role"] == "user"
    assert response["assistant_message"]["metadata_json"]["status"] == "context_loaded"
    assert "loaded recent project context" in response["assistant_message"]["content"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
