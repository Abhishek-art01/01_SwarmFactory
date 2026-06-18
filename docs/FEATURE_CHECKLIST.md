# Swarm Factory Feature Checklist

## Completed

### Feature 1: Project-Based Chat History

* [x] Project model support added
* [x] Workspace model support added
* [x] Conversation model support added
* [x] Message model support added
* [x] Azure Blob JSON state store added
* [x] Project list/create UI added
* [x] Project chat page added
* [x] Conversation sidebar added
* [x] Message history persistence added
* [x] User message saves before assistant response
* [x] Deployment now requires `AZURE_STORAGE_CONNECTION_STRING`

### Feature 2: Code Editing Memory / Context System

* [x] Code editing memory / context system foundation
* [x] Project context builder added
* [x] Recent message context added
* [x] Relevant message placeholder added
* [x] Project/workspace/conversation context added
* [x] Context preview API added
* [x] Chat flow now builds context before assistant acknowledgement
* [x] Context limits added
* [x] Tests added

### Feature 3: File Storage + File Tree Foundation

* [x] Workspace file metadata support added
* [x] File tree API added
* [x] Safe file read API added
* [x] Basic file create/update support added if appropriate
* [x] File tree connected to project context builder
* [x] Frontend file explorer added
* [x] Basic file preview added
* [x] Tests added

### Feature 4: Diff Viewer + User Approval Flow

* [x] File change proposal model added
* [x] Proposed change API added
* [x] Diff generation added
* [x] Pending changes list API added
* [x] Approve change API added
* [x] Reject change API added
* [x] Approved changes apply to workspace files
* [x] Rejected changes do not modify files
* [x] Frontend diff viewer added
* [x] Pending changes UI added
* [x] Tests added

## To Do Later

### Auth / User Ownership

* [ ] Replace `DEFAULT_USER_ID` with real multi-user authentication
* [ ] Use real logged-in user id from auth token/session
* [ ] Add project ownership checks
* [ ] Add conversation ownership checks
* [ ] Prevent users from accessing other users' projects or messages

### Agent Execution

* [ ] Replace saved acknowledgement response with real coding-agent execution
* [ ] Connect chat instruction to agent orchestration flow
* [ ] Let agent inspect project files before responding
* [ ] Let agent plan, edit files, and save changes
* [ ] Save agent run status and errors

### Storage / Scalability

* [ ] Replace simple Azure Blob JSON state with a high-concurrency database later
* [ ] Consider PostgreSQL, Azure SQL, Cosmos DB, or another scalable database
* [ ] Add safer concurrent write handling
* [ ] Add search/indexing for messages and projects
* [ ] Add backup and recovery strategy

### Future File Editing Features

* [ ] Real AI file editing
* [ ] Agent-generated change proposals
* [ ] File version rollback
* [ ] Agent run file-change tracking
* [ ] Test/build integration after edits

### Future Features Not Added Yet

* [ ] GitHub import/pull/push
* [ ] ZIP download
* [ ] Code runner / sandbox execution
* [ ] Live terminal logs
* [ ] Prompt enhancer
* [ ] Mobile app support
* [ ] Advanced multi-agent workflow
