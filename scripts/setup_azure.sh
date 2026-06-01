#!/usr/bin/env bash
# =============================================================
# Swarm Factory — Azure Resource Setup Script
# Run ONCE before first deployment.
# Usage: bash scripts/setup_azure.sh
# =============================================================
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Config — edit these before running ───────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-swarm-factory-rg}"
LOCATION="${LOCATION:-eastus}"
OPENAI_RESOURCE="${OPENAI_RESOURCE:-swarm-factory-openai}"
SEARCH_RESOURCE="${SEARCH_RESOURCE:-swarm-factory-search}"
ACR_NAME="${ACR_NAME:-swarmfactoryacr}"
CONTAINER_ENV="${CONTAINER_ENV:-swarm-factory-env}"
APP_NAME="${APP_NAME:-swarm-factory-api}"

# ── Check prerequisites ───────────────────────────────────────────────────────
command -v az   >/dev/null 2>&1 || error "Azure CLI not found. Install from https://docs.microsoft.com/cli/azure/install-azure-cli"
command -v jq   >/dev/null 2>&1 || warn  "jq not found — some output parsing may fail"

info "Checking Azure login..."
az account show >/dev/null 2>&1 || { info "Not logged in. Running az login..."; az login; }
SUBSCRIPTION=$(az account show --query id -o tsv)
success "Logged in. Subscription: $SUBSCRIPTION"

# ── 1. Resource Group ─────────────────────────────────────────────────────────
info "Creating resource group: $RESOURCE_GROUP in $LOCATION..."
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
success "Resource group ready: $RESOURCE_GROUP"

# ── 2. Azure OpenAI ───────────────────────────────────────────────────────────
info "Creating Azure OpenAI resource: $OPENAI_RESOURCE..."
az cognitiveservices account create \
    --name "$OPENAI_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --kind OpenAI \
    --sku S0 \
    --location "$LOCATION" \
    --yes \
    --output none 2>/dev/null || warn "OpenAI resource may already exist — continuing"

success "Azure OpenAI resource ready"

# ── 3. Deploy GPT-4o ──────────────────────────────────────────────────────────
info "Deploying gpt-4o model..."
az cognitiveservices account deployment create \
    --name "$OPENAI_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "gpt-4o" \
    --model-name "gpt-4o" \
    --model-version "2024-05-13" \
    --model-format OpenAI \
    --sku-capacity 10 \
    --sku-name Standard \
    --output none 2>/dev/null || warn "gpt-4o deployment may already exist"

success "gpt-4o deployed"

# ── 4. Deploy Phi-4 ──────────────────────────────────────────────────────────
info "Deploying phi-4 model..."
az cognitiveservices account deployment create \
    --name "$OPENAI_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "phi-4" \
    --model-name "phi-4" \
    --model-version "1" \
    --model-format OpenAI \
    --sku-capacity 10 \
    --sku-name Standard \
    --output none 2>/dev/null || warn "phi-4 deployment may already exist"

success "phi-4 deployed"

# ── 5. Deploy GPT-4o-mini ─────────────────────────────────────────────────────
info "Deploying gpt-4o-mini model..."
az cognitiveservices account deployment create \
    --name "$OPENAI_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "gpt-4o-mini" \
    --model-name "gpt-4o-mini" \
    --model-version "2024-07-18" \
    --model-format OpenAI \
    --sku-capacity 10 \
    --sku-name Standard \
    --output none 2>/dev/null || warn "gpt-4o-mini may already exist"

success "gpt-4o-mini deployed"

# ── 6. Get OpenAI Endpoint + Key ──────────────────────────────────────────────
info "Fetching Azure OpenAI credentials..."
OPENAI_ENDPOINT=$(az cognitiveservices account show \
    --name "$OPENAI_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.endpoint" -o tsv)

OPENAI_KEY=$(az cognitiveservices account keys list \
    --name "$OPENAI_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --query "key1" -o tsv)

success "OpenAI endpoint: $OPENAI_ENDPOINT"

# ── 7. Azure AI Search ────────────────────────────────────────────────────────
info "Creating Azure AI Search: $SEARCH_RESOURCE..."
az search service create \
    --name "$SEARCH_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --sku basic \
    --location "$LOCATION" \
    --output none 2>/dev/null || warn "Search resource may already exist"

SEARCH_ENDPOINT="https://${SEARCH_RESOURCE}.search.windows.net"
SEARCH_KEY=$(az search admin-key show \
    --service-name "$SEARCH_RESOURCE" \
    --resource-group "$RESOURCE_GROUP" \
    --query "primaryKey" -o tsv 2>/dev/null || echo "")

success "Azure AI Search ready: $SEARCH_ENDPOINT"

# ── 8. Azure Container Registry ───────────────────────────────────────────────
info "Creating Azure Container Registry: $ACR_NAME..."
az acr create \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --sku Basic \
    --admin-enabled true \
    --output none 2>/dev/null || warn "ACR may already exist"

ACR_LOGIN_SERVER=$(az acr show \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "loginServer" -o tsv)

success "ACR ready: $ACR_LOGIN_SERVER"

# ── 9. Container Apps Environment ────────────────────────────────────────────
info "Creating Container Apps environment: $CONTAINER_ENV..."
az containerapp env create \
    --name "$CONTAINER_ENV" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none 2>/dev/null || warn "Container Apps env may already exist"

success "Container Apps environment ready"

# ── 10. Write .env file ───────────────────────────────────────────────────────
ENV_FILE=".env"
info "Writing credentials to $ENV_FILE..."

cat > "$ENV_FILE" << ENVEOF
# Auto-generated by scripts/setup_azure.sh
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Azure OpenAI ──────────────────────────────────────────
AZURE_OPENAI_ENDPOINT=${OPENAI_ENDPOINT}
AZURE_OPENAI_API_KEY=${OPENAI_KEY}
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_DEPLOYMENT_GPT4O=gpt-4o
AZURE_OPENAI_DEPLOYMENT_PHI4=phi-4
AZURE_OPENAI_DEPLOYMENT_MINI=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-02-01

# ── Azure AI Search ───────────────────────────────────────
AZURE_SEARCH_ENDPOINT=${SEARCH_ENDPOINT}
AZURE_SEARCH_API_KEY=${SEARCH_KEY}
AZURE_SEARCH_INDEX_NAME=swarm-memory

# ── Azure Container Apps ──────────────────────────────────
AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION}
AZURE_RESOURCE_GROUP=${RESOURCE_GROUP}
AZURE_CONTAINER_REGISTRY=${ACR_LOGIN_SERVER}
AZURE_CONTAINER_APP_NAME=${APP_NAME}
AZURE_CONTAINER_APP_ENV=${CONTAINER_ENV}

# ── GitHub ────────────────────────────────────────────────
GITHUB_TOKEN=ghp_YOUR_TOKEN_HERE
GITHUB_ORG=YOUR_GITHUB_USERNAME

# ── Redis ─────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Bing Search ───────────────────────────────────────────
BING_SEARCH_API_KEY=YOUR_BING_KEY_HERE

# ── App ───────────────────────────────────────────────────
API_KEY=swarm-factory-dev-key
SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || echo "change-this-to-a-long-random-string")
APP_ENV=development
LOG_LEVEL=INFO
SESSION_STORE_PATH=./sessions

# ── Frontend ──────────────────────────────────────────────
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_API_KEY=swarm-factory-dev-key
ENVEOF

success ".env file written"

# ── 11. Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Azure setup complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Resource Group:      $RESOURCE_GROUP"
echo "  OpenAI Endpoint:     $OPENAI_ENDPOINT"
echo "  Search Endpoint:     $SEARCH_ENDPOINT"
echo "  Container Registry:  $ACR_LOGIN_SERVER"
echo "  Container Apps Env:  $CONTAINER_ENV"
echo ""
echo -e "${YELLOW}  NEXT STEPS:${NC}"
echo "  1. Open .env and fill in:"
echo "     - GITHUB_TOKEN  (create at github.com/settings/tokens)"
echo "     - GITHUB_ORG    (your GitHub username)"
echo "     - BING_SEARCH_API_KEY (optional — for web_search tool)"
echo ""
echo "  2. Run: docker-compose up"
echo "  3. Open: http://localhost:3000"
echo ""
