#!/usr/bin/env bash
# =============================================================
# Swarm Factory — Seed Memory Script
# Pre-populates the session store with common patterns so the
# first build has context even before any real builds run.
# Usage: bash scripts/seed_memory.sh
# =============================================================
set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }

[ -f .env ] && export $(grep -v '^#' .env | xargs) || true

SESSION_DIR="${SESSION_STORE_PATH:-./sessions}"
mkdir -p "$SESSION_DIR"

info "Seeding memory with common build patterns..."

# ── Seed 1: FastAPI REST API ───────────────────────────────────────────────────
cat > "$SESSION_DIR/seed-fastapi-rest.json" << 'EOF'
{
  "job_id": "seed-fastapi-rest",
  "requirement": "Build a REST API with FastAPI and PostgreSQL",
  "tech_stack": {
    "language": "python",
    "framework": "fastapi",
    "database": "postgresql",
    "orm": "sqlalchemy",
    "auth": "jwt"
  },
  "complexity": 6,
  "task_type": "api",
  "status": "complete",
  "seeded": true
}
EOF

# ── Seed 2: React Frontend ────────────────────────────────────────────────────
cat > "$SESSION_DIR/seed-react-frontend.json" << 'EOF'
{
  "job_id": "seed-react-frontend",
  "requirement": "Build a React TypeScript dashboard with Tailwind CSS",
  "tech_stack": {
    "language": "typescript",
    "framework": "react",
    "styling": "tailwind",
    "state": "zustand",
    "build": "vite"
  },
  "complexity": 5,
  "task_type": "frontend",
  "status": "complete",
  "seeded": true
}
EOF

# ── Seed 3: CLI Tool ──────────────────────────────────────────────────────────
cat > "$SESSION_DIR/seed-python-cli.json" << 'EOF'
{
  "job_id": "seed-python-cli",
  "requirement": "Build a Python CLI tool with Click",
  "tech_stack": {
    "language": "python",
    "framework": "click",
    "packaging": "setuptools"
  },
  "complexity": 3,
  "task_type": "cli",
  "status": "complete",
  "seeded": true
}
EOF

success "Memory seeded with 3 common patterns in $SESSION_DIR"
ls -la "$SESSION_DIR"
