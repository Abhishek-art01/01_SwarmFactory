import pytest

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
async def test_project_conversation_messages_persist_in_order():
    service = ProjectHistoryService(FakeStore())

    project = await service.create_project("user-1", "Demo", "Persistent chat")
    conversation = await service.create_conversation("user-1", project["id"], title="New conversation")

    first = await service.add_message("user-1", conversation["id"], "user", "Fix the login page")
    second = await service.add_message("user-1", conversation["id"], "assistant", "Saved for later work")

    messages = await service.get_messages("user-1", conversation["id"])
    conversations = await service.list_conversations("user-1", project["id"])

    assert [m["id"] for m in messages] == [first["id"], second["id"]]
    assert conversations[0]["title"] == "Fix the login page"


@pytest.mark.asyncio
async def test_conversations_are_separate_per_project():
    service = ProjectHistoryService(FakeStore())

    first_project = await service.create_project("user-1", "First")
    second_project = await service.create_project("user-1", "Second")
    first_conversation = await service.create_conversation("user-1", first_project["id"])
    second_conversation = await service.create_conversation("user-1", second_project["id"])

    await service.add_message("user-1", first_conversation["id"], "user", "Message A")
    await service.add_message("user-1", second_conversation["id"], "user", "Message B")

    first_messages = await service.get_messages("user-1", first_conversation["id"])
    second_messages = await service.get_messages("user-1", second_conversation["id"])

    assert first_messages[0]["content"] == "Message A"
    assert second_messages[0]["content"] == "Message B"


@pytest.mark.asyncio
async def test_project_history_blocks_other_user_access():
    service = ProjectHistoryService(FakeStore())

    project = await service.create_project("user-1", "Private")
    conversation = await service.create_conversation("user-1", project["id"])

    with pytest.raises(ForbiddenError):
        await service.list_conversations("user-2", project["id"])

    with pytest.raises(ForbiddenError):
        await service.get_messages("user-2", conversation["id"])
