# Swarm Factory

> Type a requirement. Get a working codebase.

Built for **Microsoft Build AI Hackathon 2026 — Theme 05: Agent Swarms**

## What it does

Swarm Factory deploys 7 specialized AI agents simultaneously:

| Agent     | Role |
|-----------|------|
| Planner   | Breaks requirement into ordered task graph |
| Architect | Designs tech stack, folder structure, schema |
| Coder     | Writes all source code (GPT-4o) |
| Tester    | Writes unit + integration tests |
| Reviewer  | Security, performance, best practice review |
| DevOps    | Dockerfile, CI/CD, Azure deployment |
| Mediator  | Resolves conflicts, runs quality gate |

## Output for every build

- ✅ Working GitHub repository
- ✅ Tests with 80%+ coverage
- ✅ Live Azure URL
- ✅ Dockerfile + GitHub Actions CI/CD
- ✅ Architecture decision record

## Microsoft stack

- Azure OpenAI (GPT-4o, Phi-4, GPT-4o-mini)
- AutoGen (multi-agent orchestration)
- Semantic Kernel (memory layer)
- Azure AI Search (vector store)
- Azure Container Apps (hosting)
- GitHub Actions (CI/CD)

## Quick start (under 10 minutes)

```bash
# 1. Clone
git clone https://github.com/your-org/swarm-factory
cd swarm-factory

# 2. Configure
cp .env.example .env
# Fill in your Azure keys in .env

# 3. Install backend
pip install -r requirements.txt

# 4. Install frontend
cd frontend && npm install && cd ..

# 5. Start Redis
docker run -d -p 6379:6379 --name redis redis:alpine

# 6. Start Celery worker (new terminal)
cd backend && celery -A celery_app worker --loglevel=info

# 7. Start API (new terminal)
cd backend && uvicorn api.server:app --reload

# 8. Start frontend (new terminal)
cd frontend && npm run dev

# 9. Open http://localhost:3000
```

## Built with GitHub Copilot
This project was developed using GitHub Copilot as a coding assistant,
as permitted by hackathon rules.
## Prompt : Build a hello world Flask API with one GET endpoint that returns {"message": "hello world"}
