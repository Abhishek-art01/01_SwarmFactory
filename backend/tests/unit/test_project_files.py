import pytest

from project_context.builder import ProjectContextBuilder
from project_files.service import InvalidFilePathError, ProjectFileService, normalize_file_path
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


def test_file_path_normalization_rejects_traversal():
    with pytest.raises(InvalidFilePathError):
        normalize_file_path("../secret")


def test_file_path_normalization_rejects_absolute_paths():
    with pytest.raises(InvalidFilePathError):
        normalize_file_path("/etc/passwd")


@pytest.mark.asyncio
async def test_file_creation_stores_metadata():
    history = ProjectHistoryService(FakeStore())
    files = ProjectFileService(history, FakeContentStore())
    project = await history.create_project("user-1", "Demo")
    workspace_id = project["default_workspace_id"]

    saved = await files.upsert_file("user-1", project["id"], workspace_id, "src/App.tsx", "export default App;")

    assert saved["path"] == "src/App.tsx"
    assert saved["name"] == "App.tsx"
    assert saved["language"] == "typescript"
    assert saved["size"] == len("export default App;".encode("utf-8"))
    assert saved["hash"]
    assert saved["content_blob_name"].endswith(f"{workspace_id}/src/App.tsx")


@pytest.mark.asyncio
async def test_file_tree_returns_nested_structure():
    history = ProjectHistoryService(FakeStore())
    files = ProjectFileService(history, FakeContentStore())
    project = await history.create_project("user-1", "Demo")
    workspace_id = project["default_workspace_id"]

    await files.upsert_file("user-1", project["id"], workspace_id, "src/App.tsx", "app")
    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "readme")

    tree = await files.list_file_tree("user-1", project["id"], workspace_id)

    assert [node["name"] for node in tree["tree"]] == ["src", "README.md"]
    assert tree["tree"][0]["children"][0]["path"] == "src/App.tsx"


@pytest.mark.asyncio
async def test_file_content_can_be_read_for_safe_files():
    history = ProjectHistoryService(FakeStore())
    content_store = FakeContentStore()
    files = ProjectFileService(history, content_store)
    project = await history.create_project("user-1", "Demo")
    workspace_id = project["default_workspace_id"]

    await files.upsert_file("user-1", project["id"], workspace_id, "README.md", "hello")
    content = await files.read_file("user-1", project["id"], workspace_id, "README.md")

    assert content["content"] == "hello"
    assert content["truncated"] is False


@pytest.mark.asyncio
async def test_env_file_read_is_blocked():
    history = ProjectHistoryService(FakeStore())
    files = ProjectFileService(history, FakeContentStore())
    project = await history.create_project("user-1", "Demo")
    workspace_id = project["default_workspace_id"]

    with pytest.raises(InvalidFilePathError):
        await files.read_file("user-1", project["id"], workspace_id, ".env")


@pytest.mark.asyncio
async def test_file_tree_validates_project_workspace_ownership():
    history = ProjectHistoryService(FakeStore())
    files = ProjectFileService(history, FakeContentStore())
    project = await history.create_project("user-1", "Demo")
    workspace_id = project["default_workspace_id"]

    with pytest.raises(ForbiddenError):
        await files.list_file_tree("user-2", project["id"], workspace_id)


@pytest.mark.asyncio
async def test_context_builder_includes_file_tree_metadata_without_content():
    history = ProjectHistoryService(FakeStore())
    file_service = ProjectFileService(history, FakeContentStore())
    builder = ProjectContextBuilder(history, file_service)
    project = await history.create_project("user-1", "Demo")
    workspace_id = project["default_workspace_id"]
    conversation = await history.create_conversation("user-1", project["id"], workspace_id=workspace_id)

    await file_service.upsert_file("user-1", project["id"], workspace_id, "src/App.tsx", "secret_key=abc123")

    context = await builder.build_project_context(project["id"], conversation["id"], "user-1")

    assert context["file_tree"][0]["path"] == "src/App.tsx"
    assert context["file_tree"][0]["language"] == "typescript"
    assert "secret_key" not in str(context["file_tree"])
