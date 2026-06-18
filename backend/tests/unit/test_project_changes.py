import pytest

from project_changes.service import ChangeConflictError, InvalidChangeStatusError, ProjectChangeService
from project_files.service import InvalidFilePathError, ProjectFileService
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
            "files": dict(self.state.get("files", {})),
            "file_changes": dict(self.state.get("file_changes", {})),
        }

    async def save(self, state):
        self.state = state


class FakeContentStore:
    def __init__(self):
        self.blobs = {}

    async def write_text(self, blob_name, content):
        self.blobs[blob_name] = content

    async def read_text(self, blob_name):
        return self.blobs[blob_name]


async def _services():
    history = ProjectHistoryService(FakeStore())
    content_store = FakeContentStore()
    files = ProjectFileService(history, content_store)
    changes = ProjectChangeService(files)
    project = await history.create_project("user-1", "Demo")
    return history, files, changes, project, project["default_workspace_id"]


@pytest.mark.asyncio
async def test_create_proposed_change_does_not_modify_file_and_returns_diff():
    _, files, changes, project, workspace_id = await _services()
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello old\n")

    change = await changes.create_change_proposal(
        "user-1",
        project["id"],
        workspace_id,
        "README.md",
        "hello new\n",
    )
    content = await files.read_file("user-1", project["id"], workspace_id, "README.md")

    assert content["content"] == "hello old\n"
    assert change["status"] == "pending"
    assert "--- a/README.md" in change["diff"]
    assert "+hello new" in change["diff"]


@pytest.mark.asyncio
async def test_approving_proposed_change_updates_file_content():
    _, files, changes, project, workspace_id = await _services()
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello old\n")
    change = await changes.create_change_proposal("user-1", project["id"], workspace_id, "README.md", "hello new\n")

    applied = await changes.approve_change("user-1", project["id"], workspace_id, change["id"])
    content = await files.read_file("user-1", project["id"], workspace_id, "README.md")

    assert applied["status"] == "applied"
    assert content["content"] == "hello new\n"


@pytest.mark.asyncio
async def test_rejecting_proposed_change_does_not_update_file_content():
    _, files, changes, project, workspace_id = await _services()
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello old\n")
    change = await changes.create_change_proposal("user-1", project["id"], workspace_id, "README.md", "hello new\n")

    rejected = await changes.reject_change("user-1", project["id"], workspace_id, change["id"])
    content = await files.read_file("user-1", project["id"], workspace_id, "README.md")

    assert rejected["status"] == "rejected"
    assert content["content"] == "hello old\n"


@pytest.mark.asyncio
async def test_applying_rejected_or_applied_change_is_blocked():
    _, files, changes, project, workspace_id = await _services()
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello old\n")
    rejected = await changes.create_change_proposal("user-1", project["id"], workspace_id, "README.md", "hello new\n")
    await changes.reject_change("user-1", project["id"], workspace_id, rejected["id"])

    with pytest.raises(InvalidChangeStatusError):
        await changes.approve_change("user-1", project["id"], workspace_id, rejected["id"])

    applied = await changes.create_change_proposal("user-1", project["id"], workspace_id, "README.md", "hello new\n")
    await changes.approve_change("user-1", project["id"], workspace_id, applied["id"])
    with pytest.raises(InvalidChangeStatusError):
        await changes.approve_change("user-1", project["id"], workspace_id, applied["id"])


@pytest.mark.asyncio
async def test_change_proposal_rejects_unsafe_paths():
    _, _, changes, project, workspace_id = await _services()

    with pytest.raises(InvalidFilePathError):
        await changes.create_change_proposal("user-1", project["id"], workspace_id, "../README.md", "new")

    with pytest.raises(InvalidFilePathError):
        await changes.create_change_proposal("user-1", project["id"], workspace_id, ".env", "TOKEN=value")


@pytest.mark.asyncio
async def test_change_proposal_validates_ownership():
    _, files, changes, project, workspace_id = await _services()
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello old\n")

    with pytest.raises(ForbiddenError):
        await changes.create_change_proposal("user-2", project["id"], workspace_id, "README.md", "hello new\n")


@pytest.mark.asyncio
async def test_stale_proposal_conflict_is_detected_before_approval():
    _, files, changes, project, workspace_id = await _services()
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello old\n")
    change = await changes.create_change_proposal("user-1", project["id"], workspace_id, "README.md", "hello proposed\n")
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "manual edit\n")

    with pytest.raises(ChangeConflictError):
        await changes.approve_change("user-1", project["id"], workspace_id, change["id"])

    content = await files.read_file("user-1", project["id"], workspace_id, "README.md")
    assert content["content"] == "manual edit\n"


@pytest.mark.asyncio
async def test_create_change_proposal_applies_new_file_only_after_approval():
    _, files, changes, project, workspace_id = await _services()
    change = await changes.create_change_proposal(
        "user-1",
        project["id"],
        workspace_id,
        "docs/new.md",
        "created\n",
        change_type="create",
    )

    with pytest.raises(Exception):
        await files.read_file("user-1", project["id"], workspace_id, "docs/new.md")

    await changes.approve_change("user-1", project["id"], workspace_id, change["id"])
    content = await files.read_file("user-1", project["id"], workspace_id, "docs/new.md")
    assert content["content"] == "created\n"
