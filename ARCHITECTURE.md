# Swarm Factory — Architecture Document

> Built for Microsoft Build AI Hackathon 2026 — Theme 05: Agent Swarms

---

## System Overview

Swarm Factory converts a plain English software requirement into a fully deployed, tested, production-ready codebase using a swarm of 7 specialized AI agents powered by Microsoft Azure AI.

```
User Input (plain English)
        │
        ▼
┌───────────────┐     ┌──────────────────────────────────────┐
│  React UI     │────▶│  FastAPI  (POST /api/generate)       │
│  (Frontend)   │     │  Returns: { job_id }                 │
└───────────────┘     └──────────────┬───────────────────────┘
        │                            │ Celery task enqueued
        │ WebSocket /ws/{job_id}     ▼
        │                   ┌────────────────┐
        │◀──────────────────│  Celery Worker │
        │  Real-time events  └───────┬────────┘
        │                           │
        │                           ▼
        │              ┌────────────────────────┐
        │              │   Swarm Controller     │
        │              │   (7-agent pipeline)   │
        │              └────────────────────────┘
        │                           │
        ▼                           ▼
  Live Dashboard          GitHub Repo + Azure URL
```

---

## The 7-Agent Pipeline

Agents execute in this order, with stages 3–5 running in parallel:

```
Stage 1: Planner Agent
  Input:  Plain English requirement
  Output: Task graph (DAG of subtasks)
  Model:  GPT-4o | Temperature: 0.2

Stage 2: Architect Agent
  Input:  Task graph
  Output: Tech stack, folder structure, API contracts, dependencies
  Model:  GPT-4o | Temperature: 0.2

Stage 3: ┌─ Coder Agent ──────────────────────────────────────┐
Stage 4: │  Tester Agent      (parallel via asyncio.gather)   │
Stage 5: └─ Reviewer Agent ──────────────────────────────────-┘
  Input:  Architect output
  Output: Source files, test files, review score
  Model:  GPT-4o (Coder), GPT-4o (Tester), GPT-4o (Reviewer)

  ↓ Quality Gate: if review score < 5/10 → retry coder (max 2x)

Stage 6: Mediator Agent
  Input:  All agent outputs
  Output: FinalCodebase (merged, conflict-resolved, deduplicated)
  Model:  GPT-4o | Temperature: 0.2

Stage 7: DevOps Agent
  Input:  FinalCodebase
  Output: DeployOutput (GitHub URL + Azure URL)
  Tools:  git_ops → docker_builder → azure_deploy
```

---

## Fallback Chain

Every agent call is wrapped by `orchestrator/fallback_chain.py`:

```
GPT-4o (primary)
    │ fails?
    ▼
Phi-4 (secondary)
    │ fails?
    ▼
GPT-4o-mini (tertiary)
    │ fails?
    ▼
Cached template output (never crashes)
```

The system always produces something — it never returns a blank error.

---

## Real-Time Event Flow

```
Celery Worker
    │ publishes to Redis Pub/Sub channel: "job:{job_id}:events"
    ▼
Redis Pub/Sub
    │ WebSocket handler subscribes to channel
    ▼
api/websocket.py
    │ forwards every event to connected browser client
    ▼
React UI (useSwarm hook)
    │ updates agent cards, pipeline bar, file tree, live log
    ▼
User sees live progress
```

Event shapes emitted:
```json
{ "type": "agent_update", "agent": "coder", "status": "running", "output": "..." }
{ "type": "file_written", "filename": "main.py" }
{ "type": "log", "message": "Quality gate passed: 8/10" }
{ "type": "complete", "github_url": "...", "azure_url": "...", "coverage": 92 }
{ "type": "error", "message": "Agent failed: ..." }
```

---

## Microsoft Stack Usage

| Service | Role | File |
|---|---|---|
| **Azure OpenAI GPT-4o** | Primary model for all 7 agents | `agents/base_agent.py` |
| **Azure OpenAI Phi-4** | Fast fallback model | `models/phi4.py` |
| **Azure OpenAI GPT-4o-mini** | Final fallback model | `models/azure_openai.py` |
| **AutoGen** | Agent base class + GroupChat pattern | `agents/base_agent.py` |
| **Semantic Kernel** | Memory plugin + embeddings | `memory/semantic_memory.py` |
| **Azure AI Search** | Vector store for session memory | `memory/azure_search.py` |
| **Azure Container Apps** | Hosts the FastAPI backend | `scripts/deploy.sh` |
| **Azure Container Registry** | Stores generated app Docker images | `tools/docker_builder.py` |
| **GitHub Actions** | CI/CD for our codebase | `.github/workflows/` |

---

## Folder Structure

```
swarm-factory/
├── frontend/                    React + TypeScript + Tailwind
│   └── src/
│       ├── pages/               Home, Dashboard, Output
│       ├── components/          AgentCard, PipelineBar, FileTree, LiveLog...
│       ├── hooks/               useSwarm, useJob, useStream
│       └── lib/                 api.ts, websocket.ts
│
├── backend/
│   ├── api/                     FastAPI server + routes + WebSocket
│   │   ├── routes/              generate, status, output, health
│   │   ├── middleware/          auth, rate_limit, error_handler
│   │   └── websocket.py         Redis Pub/Sub → WebSocket bridge
│   │
│   ├── agents/                  All 7 agent implementations
│   │   ├── base_agent.py        Abstract base with LLM call + retry
│   │   ├── planner_agent.py     Agent 1: task graph
│   │   ├── architect_agent.py   Agent 2: tech stack + structure
│   │   ├── coder_agent.py       Agent 3: source code
│   │   ├── test_agent.py        Agent 4: test suite
│   │   ├── reviewer_agent.py    Agent 5: security + quality review
│   │   ├── mediator_agent.py    Agent 6: merge + quality gate
│   │   └── devops_agent.py      Agent 7: GitHub + Azure deploy
│   │
│   ├── orchestrator/            Pipeline coordination
│   │   ├── swarm_controller.py  Main pipeline runner
│   │   ├── parallel_runner.py   asyncio.gather fan-out
│   │   ├── fallback_chain.py    GPT-4o → Phi-4 → GPT-4o-mini
│   │   ├── quality_gate.py      Block bad outputs
│   │   └── merger.py            Combine agent outputs
│   │
│   ├── memory/                  Session + vector memory
│   │   ├── session_store.py     Disk-based JSON sessions
│   │   ├── context_injector.py  Inject past context into prompts
│   │   ├── azure_search.py      Azure AI Search vector store
│   │   └── semantic_memory.py   Semantic Kernel plugin
│   │
│   ├── tools/                   Execution tools
│   │   ├── file_writer.py       Atomic file write
│   │   ├── test_runner.py       pytest + coverage
│   │   ├── linter.py            ruff auto-fix
│   │   ├── git_ops.py           GitHub repo creation + push
│   │   ├── docker_builder.py    Docker build + ACR push
│   │   └── azure_deploy.py      Azure Container Apps deploy
│   │
│   ├── models/                  LLM wrappers
│   │   ├── azure_openai.py      GPT-4o + retry
│   │   ├── phi4.py              Phi-4 wrapper
│   │   └── model_router.py      Complexity → model selector
│   │
│   ├── core/                    Shared infrastructure
│   │   ├── config.py            Pydantic settings
│   │   ├── logger.py            Structured logging
│   │   └── exceptions.py        Typed exceptions
│   │
│   ├── queue/                   Job queue
│   │   ├── job_store.py         Redis job state
│   │   └── job_processor.py     Celery task runner
│   │
│   └── celery_app.py            Celery app definition
│
├── infra/
│   ├── Dockerfile               Production container
│   ├── docker-compose.yml       Local dev stack
│   ├── nginx.conf               Reverse proxy
│   └── azure/                   Bicep IaC templates
│
├── scripts/
│   ├── setup_azure.sh           One-time Azure provisioning
│   ├── deploy.sh                Production deploy
│   └── seed_memory.sh           Pre-seed memory store
│
├── .github/workflows/           CI/CD pipelines
├── .env.example                 Required environment variables
├── requirements.txt             Python dependencies
├── docker-compose.yml           Root dev compose
└── README.md
```

---

## Data Models (Integration Contracts)

These Pydantic models are the contracts between agents. Do not rename fields.

```python
# Agent 1 output
class PlannerOutput(BaseModel):
    task_type: str        # "api" | "frontend" | "cli" | "fullstack"
    complexity: int       # 1-10
    language: str
    framework: str
    tasks: list[Task]
    summary: str

# Agent 2 output
class ArchitectOutput(BaseModel):
    tech_stack: dict[str, str]
    folder_structure: dict
    dependencies: list[str]
    api_contracts: list[ApiContract]
    database_schema: dict | None
    env_vars_needed: list[str]

# Agent 3 output
class CoderOutput(BaseModel):
    files: dict[str, str]       # {path: content}
    dependencies: list[str]
    entry_point: str
    start_command: str

# Agent 4 output
class TestOutput(BaseModel):
    test_files: dict[str, str]
    coverage_target: int         # always 80
    test_command: str

# Agent 5 output
class ReviewOutput(BaseModel):
    score: int                   # 1-10
    approved: bool               # score >= 5
    issues: list[ReviewIssue]
    summary: str

# Agent 6 output
class FinalCodebase(BaseModel):
    files: dict[str, str]
    test_files: dict[str, str]
    dependencies: list[str]
    entry_point: str
    start_command: str
    test_command: str
    conflicts_resolved: list[str]
    quality_score: int

# Agent 7 output
class DeployOutput(BaseModel):
    github_url: str
    azure_url: str
    dockerfile_path: str
    ci_workflow_path: str
    deploy_success: bool
    image_uri: str
    error: str | None
```

---

## Quality Standards

- All LLM calls: `temperature=0.2` for consistent JSON output
- All LLM calls: retry up to 3× with exponential backoff (tenacity)
- All file writes: atomic (temp → verify → rename)
- All agent outputs: validated with Pydantic before downstream use
- Generated code: auto-linted with ruff before commit
- Test coverage: minimum 80% enforced by quality gate
- Security scan: reviewer checks OWASP top 10 before mediator runs
- Fallback chain: system never fully halts — always returns something

---

## Local Development

```bash
# Prerequisites: Python 3.11+, Node 20+, Docker

cp .env.example .env        # fill in Azure keys
pip install -r requirements.txt
cd frontend && npm install && cd ..

# Start all services
docker-compose up

# Or run manually:
docker run -d -p 6379:6379 redis:alpine
cd backend && celery -A celery_app worker --loglevel=info &
cd backend && uvicorn api.server:app --reload &
cd frontend && npm run dev
```

---

## Deployment

```bash
# One-time Azure setup
bash scripts/setup_azure.sh

# Deploy to production
bash scripts/deploy.sh
```

---

*Built with GitHub Copilot as permitted by hackathon rules.*
