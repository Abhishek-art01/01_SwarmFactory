# Swarm Factory 🤖🏭

> Type a requirement. Get a working codebase. Deployed and tested in minutes.

Built for the **Microsoft Build AI Hackathon 2026 — Theme 05: Agent Swarms**.

---

## 📖 Overview

Swarm Factory is an autonomous multi-agent platform that translates plain-English requirements into fully deployed, production-ready codebases. By leveraging a coordinated swarm of **7 specialized AI agents**, it handles planning, design, coding, testing, review, and DevOps pipeline setup completely autonomously.

```mermaid
graph TD
    User([User Requirement]) --> Planner[1. Planner Agent]
    Planner --> Architect[2. Architect Agent]
    
    subgraph Parallel Stage
        Architect --> Coder[3. Coder Agent]
        Architect --> Tester[4. Tester Agent]
        Architect --> Reviewer[5. Reviewer Agent]
    end
    
    Coder & Tester & Reviewer --> Gate{Quality Gate}
    Gate -- Score < 50/100 --> Coder
    Gate -- Score >= 50/100 --> Mediator[6. Mediator Agent]
    
    Mediator --> DevOps[7. DevOps Agent]
    DevOps --> Deploy[Live Azure App & GitHub Repo]
```

### The 7-Agent Pipeline

| Agent | Role | Focus | Model Configuration |
|---|---|---|---|
| **Planner** | Task Decomposer | Breaks requirements into an ordered task graph (DAG). | GPT-4o (`temp=0.2`) |
| **Architect** | Stack Designer | Designs tech stack, directory structure, and API contracts. | GPT-4o (`temp=0.2`) |
| **Coder** | Software Engineer | Writes all application and source code. | GPT-4o (`temp=0.2`) |
| **Tester** | QA Engineer | Writes unit & integration test suites. | GPT-4o (`temp=0.2`) |
| **Reviewer** | Security Auditor | Reviews code for security (OWASP Top 10), lint, and best practices. | GPT-4o (`temp=0.2`) |
| **Mediator** | Conflict Resolver | Resolves code merge conflicts and enforces the Quality Gate. | GPT-4o (`temp=0.2`) |
| **DevOps** | System Deployer | Sets up Docker, GitHub actions CI/CD, and deploys to Azure. | GPT-4o (`temp=0.2`) |

---

## 🛠️ Microsoft Stack & Technologies

*   **Azure OpenAI**: Powering the multi-agent orchestration (utilizing `gpt-4o` as primary, `phi-4` as secondary fallback, and `gpt-4o-mini` as tertiary fallback).
*   **AutoGen**: Orchestrates multi-agent group conversations.
*   **Semantic Kernel**: Implements the memory layer and handles embeddings.
*   **Azure AI Search**: Acts as the high-performance vector store for long-term session memory.
*   **Azure Container Apps & Container Registry (ACR)**: Hosts the backend and manages Docker containers.
*   **GitHub Actions**: Powers the autonomous CI/CD pipelines.

---

## 🚀 Quick Start (Local Development)

You can run Swarm Factory locally using **Azure OpenAI**.

### 1. Prerequisites
Ensure you have the following installed:
*   Python 3.11+
*   Node.js 20+
*   Docker & Docker Compose

### 2. Clone and Setup Dependencies
```bash
# Clone the repository
git clone https://github.com/your-org/swarm-factory
cd swarm-factory

# Copy the environment file template
cp .env.example .env

# Install Backend dependencies
pip install -r requirements.txt

# Install Frontend dependencies
cd frontend && npm install && cd ..
```

### 3. Configure the Environment (`.env`)
Open the newly created `.env` file and fill in your Azure credentials.
The stack runs exclusively on Azure OpenAI — no other providers are used.

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-openai-key-here
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_DEPLOYMENT_GPT4O=gpt-4o
AZURE_OPENAI_DEPLOYMENT_PHI4=phi-4
AZURE_OPENAI_DEPLOYMENT_MINI=gpt-4o-mini
```

### 4. Start Local Services
Launch the stack in three simple steps (use separate terminals or run in background):

#### Step A: Spin up Redis
```bash
docker run -d -p 6379:6379 --name redis redis:alpine
```

#### Step B: Start Celery Worker & Backend API
```bash
# Start Celery worker
cd backend && celery -A celery_app worker --loglevel=info

# In another terminal, start the FastAPI server
cd backend && uvicorn api.server:app --reload
```

#### Step C: Start Frontend React App
```bash
cd frontend && npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to view the Swarm Factory Dashboard.

### Frontend Vite dev proxy (local development)

The frontend uses Vite's dev proxy to forward /api and /ws to the backend on the same origin. For local/Codespace development leave the following variables empty so the frontend automatically proxies requests to the running backend (localhost:8000).

```env
VITE_API_BASE_URL=
VITE_API_URL=
VITE_WS_BASE_URL=
VITE_WS_URL=
VITE_API_KEY=swarm-factory-dev-key
```

The empty values tell Vite to proxy /api and /ws requests to the same origin — meaning the frontend automatically hits localhost:8000 without hardcoding any host. This is the correct setup for local/Codespace dev.

What each variable means — fill only if deploying to production:

- VITE_API_BASE_URL: Base URL for REST calls (/api/generate etc.) — Fill when deploying frontend separately from backend
- VITE_API_URL: Alias for the above — Same as above
- VITE_WS_BASE_URL: Base URL for WebSocket (/ws/job_id) — Fill when deploying to Azure; use wss://your-app.azurecontainerapps.io
- VITE_WS_URL: Alias for the above — Same as above
- VITE_API_KEY: Sent as X-API-Key header on every request — Always; must match backend API_KEY in root .env

---

## ☁️ Azure Infrastructure Provisioning

Swarm Factory requires a few Azure resources to deploy generated applications to the cloud. You can set them up using either the automated script or the legacy manual CLI commands.

### Method 1: Automated Script (Recommended)
This script registers all required resource providers, provisions Azure resources, and automatically configures your local `.env` file with the endpoints and keys.

```bash
# Run the automated setup script
bash scripts/setup_azure.sh
```

**What the script provisions:**
1.  Resource Group: `swarm-factory-rg`
2.  Azure OpenAI: `swarm-factory-openai` (with `gpt-4o` and `gpt-4o-mini` deployments)
3.  Azure AI Search: `swarm-factory-search` (basic SKU)
4.  Azure Container Registry (ACR): `swarmfactoryacr`
5.  Azure Container Apps Environment: `swarm-factory-env`

---

### Method 2: Manual CLI Setup (Legacy / Alternative)
If you prefer to configure resources manually or need fine-grained control over the creation process, run these Azure CLI commands:

```bash
# 1. Login to Azure
az login

# 2. Register required resource providers
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.ContainerRegistry --wait

# 3. Create the Resource Group
az group create --name swarm-factory-rg --location eastus

# 4. Create the Azure Container Registry (ACR)
az acr create \
  --name swarmfactoryacr \
  --resource-group swarm-factory-rg \
  --sku Basic \
  --admin-enabled true

# 5. Create the Container Apps Environment
az containerapp env create \
  --name swarm-factory-env \
  --resource-group swarm-factory-rg \
  --location eastus
```

> [!NOTE]
> If you deploy manually, make sure to manually update your `.env` file with the resource endpoints, keys, and IDs.

---

## 🚢 Deploying to Azure

Once your Azure resources are provisioned and your `.env` is configured, you can build and deploy the Swarm Factory application to production:

```bash
# Run the deployment script
bash scripts/deploy.sh
```

This script:
1.  Builds the production assets for the React frontend (`frontend/dist/`).
2.  Builds the Docker container image utilizing the `infra/Dockerfile`.
3.  Pushes the container image to your Azure Container Registry (ACR).
4.  Deploys or updates the Azure Container App hosting the backend API.
5.  Outputs the live URL of your deployment (e.g. `https://swarm-factory-api.azurecontainerapps.io`).

---

## 🤝 Contributing & Disclaimers

This project was developed using **GitHub Copilot** as an AI coding assistant, in compliance with the hackathon rules.

For a detailed walkthrough of the internal components and data schemas, please refer to [ARCHITECTURE.md](file:///workspaces/01_SwarmFactory/ARCHITECTURE.md).

## 🐳 Running with Docker

Run the project with Docker locally. Ensure .env is configured (copy .env.example -> .env) before starting.

1) Build images

```bash
# Backend (from repo root)
docker build -f backend/Dockerfile -t swarm-factory-backend:latest ./backend

# Frontend (if Dockerfile exists in frontend)
docker build -f frontend/Dockerfile -t swarm-factory-frontend:latest ./frontend

# (Optional) infra image used for production builds
# docker build -f infra/Dockerfile -t swarm-factory-infra:latest ./infra
```

2) Run required services and app containers

```bash
# Create a network
docker network create swarm-net || true

# Run Redis
docker run -d --name redis --network swarm-net -p 6379:6379 redis:alpine

# Run backend (exposes API on :8000)
docker run -d --name swarm-backend --network swarm-net --env-file .env -p 8000:8000 swarm-factory-backend:latest

# Run frontend (exposes UI on :3000)
docker run -d --name swarm-frontend --network swarm-net -p 3000:3000 swarm-factory-frontend:latest
```

Open http://localhost:3000 and verify the backend is reachable at http://localhost:8000.

3) Optional: docker-compose example

Create a docker-compose.yml in repo root and run `docker compose up --build`:

```yaml
version: "3.8"
services:
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - redis
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    depends_on:
      - backend
networks:
  default:
    name: swarm-net
```

Notes:
- If any Dockerfile paths differ, update the -f / build.context paths accordingly.
- This runs the app locally for development/testing. For production, use the existing infra/deploy scripts to push to ACR and deploy to Azure Container Apps.

