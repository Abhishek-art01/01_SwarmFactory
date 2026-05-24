#!/usr/bin/env bash
# =============================================================
# Swarm Factory — Production Deployment Script
# Builds, pushes, and deploys the app to Azure Container Apps.
# Usage: bash scripts/deploy.sh
# =============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# Load .env
[ -f .env ] && export $(grep -v '^#' .env | xargs) || error ".env not found. Run scripts/setup_azure.sh first."

# Validate required vars
: "${AZURE_CONTAINER_REGISTRY:?Set AZURE_CONTAINER_REGISTRY in .env}"
: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in .env}"
: "${AZURE_CONTAINER_APP_NAME:?Set AZURE_CONTAINER_APP_NAME in .env}"
: "${AZURE_CONTAINER_APP_ENV:?Set AZURE_CONTAINER_APP_ENV in .env}"

IMAGE_TAG="${AZURE_CONTAINER_REGISTRY}/swarm-factory:$(git rev-parse --short HEAD 2>/dev/null || echo latest)"

# ── 1. Build frontend ─────────────────────────────────────────────────────────
info "Building React frontend..."
cd frontend
VITE_API_URL="https://${AZURE_CONTAINER_APP_NAME}.azurecontainerapps.io" \
VITE_WS_URL="wss://${AZURE_CONTAINER_APP_NAME}.azurecontainerapps.io" \
npm run build
cd ..
success "Frontend built → frontend/dist/"

# ── 2. Build Docker image ─────────────────────────────────────────────────────
info "Building Docker image: $IMAGE_TAG"
docker build -t "$IMAGE_TAG" -f infra/Dockerfile .
success "Image built"

# ── 3. Push to ACR ───────────────────────────────────────────────────────────
info "Logging in to ACR..."
az acr login --name "$(echo "$AZURE_CONTAINER_REGISTRY" | cut -d. -f1)"

info "Pushing image to ACR..."
docker push "$IMAGE_TAG"
success "Image pushed: $IMAGE_TAG"

# ── 4. Deploy to Container Apps ───────────────────────────────────────────────
info "Deploying to Azure Container Apps: $AZURE_CONTAINER_APP_NAME..."

# Build env vars string from .env for the container
ENV_VARS="AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT} \
AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY} \
AZURE_OPENAI_DEPLOYMENT_GPT4O=${AZURE_OPENAI_DEPLOYMENT_GPT4O} \
AZURE_OPENAI_DEPLOYMENT_PHI4=${AZURE_OPENAI_DEPLOYMENT_PHI4} \
AZURE_OPENAI_DEPLOYMENT_MINI=${AZURE_OPENAI_DEPLOYMENT_MINI} \
REDIS_URL=${REDIS_URL} \
API_KEY=${API_KEY} \
SECRET_KEY=${SECRET_KEY} \
APP_ENV=production \
GITHUB_TOKEN=${GITHUB_TOKEN} \
GITHUB_ORG=${GITHUB_ORG}"

# Check if app exists
if az containerapp show --name "$AZURE_CONTAINER_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" &>/dev/null; then
    info "Updating existing Container App..."
    az containerapp update \
        --name "$AZURE_CONTAINER_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --image "$IMAGE_TAG" \
        --output none
else
    info "Creating new Container App..."
    az containerapp create \
        --name "$AZURE_CONTAINER_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --environment "$AZURE_CONTAINER_APP_ENV" \
        --image "$IMAGE_TAG" \
        --target-port 8000 \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 5 \
        --cpu 1.0 \
        --memory 2.0Gi \
        --env-vars $ENV_VARS \
        --output none
fi

# ── 5. Get live URL ───────────────────────────────────────────────────────────
LIVE_URL=$(az containerapp show \
    --name "$AZURE_CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

success "Deployment complete!"
echo ""
echo "  Live URL: https://${LIVE_URL}"
echo "  Health:   https://${LIVE_URL}/health"
echo ""
