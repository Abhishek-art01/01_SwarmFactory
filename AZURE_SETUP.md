# Azure Setup Guide

## Current Status
Using **Google Gemini** (free) while waiting for Azure OpenAI quota.
When quota is approved: change `LLM_PROVIDER=azure` in `.env` — that's it.

## Quick Start (run now, no Azure quota needed)

```bash
# 1. Copy env file
cp .env.example .env

# 2. Fill in these 3 lines in .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-from-aistudio.google.com
GROQ_API_KEY=your-key-from-console.groq.com

# 3. Install deps
pip install -r requirements.txt
cd frontend && npm install && cd ..

# 4. Start Redis
docker run -d -p 6379:6379 --name redis redis:alpine

# 5. Start Celery (new terminal)
cd backend && celery -A celery_app worker --loglevel=info

# 6. Start API (new terminal)
cd backend && uvicorn api.server:app --reload

# 7. Start Frontend (new terminal)
cd frontend && npm run dev

# 8. Open http://localhost:3000
```

## Azure Resources (already created)

| Resource | Status |
|---|---|
| Resource Group `swarm-factory-rg` | ✅ Created |
| Azure OpenAI `swarm-factory-openai` | ✅ Created |
| GPT-4o deployment | ⏳ Waiting for quota approval |
| Container Registry | Run step below |
| Container Apps | Run step below |

## Finish Azure setup (no quota needed for these)

```bash
# Register providers
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.ContainerRegistry --wait

# Container Registry
az acr create \
  --name swarmfactoryacr \
  --resource-group swarm-factory-rg \
  --sku Basic --admin-enabled true

# Container Apps environment
az containerapp env create \
  --name swarm-factory-env \
  --resource-group swarm-factory-rg \
  --location eastus
```

## Switch to Azure when quota approved

```bash
# In .env, change ONE line:
LLM_PROVIDER=azure
# Also fill in:
AZURE_OPENAI_ENDPOINT=https://swarm-factory-openai-ae4c3.openai.azure.com/
AZURE_OPENAI_API_KEY=EplOynnxx6g...  # your key
```
