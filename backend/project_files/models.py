from typing import Any, Literal, TypedDict


class FileMetadata(TypedDict):
    id: str
    project_id: str
    workspace_id: str
    user_id: str
    path: str
    name: str
    language: str
    size: int
    hash: str
    content_blob_name: str
    created_at: str
    updated_at: str


class FileTreeNode(TypedDict, total=False):
    name: str
    path: str
    type: Literal["directory", "file"]
    children: list["FileTreeNode"]
    language: str
    size: int
    hash: str
    updated_at: str


class FileTreeResponse(TypedDict):
    workspace_id: str
    files: list[FileMetadata]
    tree: list[FileTreeNode]


class FileContentResponse(TypedDict):
    file: FileMetadata
    content: str
    truncated: bool
    redacted: bool


State = dict[str, dict[str, Any]]
