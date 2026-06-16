#!/usr/bin/env bash
# =============================================================
# Swarm Factory — Fast Azure Container Apps Deployment
# Builds the local image, pushes it to ACR, updates Container Apps,
# and verifies the live app.
#
# Usage:
#   bash scripts/deploy.sh
#   TAG=my-test bash scripts/deploy.sh
#   SKIP_BUILD=1 IMAGE=swarmfactoryacr.azurecr.io/swarm-factory-api:tag bash scripts/deploy.sh
# =============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

load_env() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  else
    warn ".env not found; using defaults and current environment"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || error "$1 is required but was not found"
}

trim_trailing_space() {
  printf '%s' "$1" | sed 's/[[:space:]]*$//'
}

require_var() {
  local name="$1"
  [[ -n "${!name:-}" ]] || error "$name is required. Set it in .env or export it before running."
}

load_env
require_cmd az
require_cmd git
require_cmd curl

: "${AZURE_RESOURCE_GROUP:=swarm-factory-rg}"
: "${AZURE_CONTAINER_APP_NAME:=swarm-factory-api}"
: "${AZURE_WORKER_APP_NAME:=swarm-factory-worker}"
: "${AZURE_CONTAINER_APP_ENV:=swarm-factory-env}"
: "${AZURE_CONTAINER_REGISTRY:=swarmfactoryacr.azurecr.io}"
: "${IMAGE_REPOSITORY:=swarm-factory-api}"
: "${DOCKERFILE:=infra/Dockerfile}"
: "${SKIP_BUILD:=0}"
: "${DEPLOY_WORKER:=1}"
: "${CELERY_CONCURRENCY:=2}"

require_var AZURE_RESOURCE_GROUP
require_var AZURE_CONTAINER_APP_NAME
require_var AZURE_CONTAINER_REGISTRY

info "Checking Azure login..."
az account show >/dev/null 2>&1 || az login >/dev/null
success "Azure CLI is authenticated"

get_current_env() {
  local name="$1"
  local app_name="${2:-$AZURE_CONTAINER_APP_NAME}"
  az containerapp show \
    --name "$app_name" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.template.containers[0].env[?name=='${name}'].value | [0]" \
    -o tsv 2>/dev/null || true
}

hydrate_from_azure() {
  if ! az containerapp show --name "$AZURE_CONTAINER_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
    return
  fi

  local current
  for name in AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY AZURE_SEARCH_ENDPOINT AZURE_SEARCH_API_KEY REDIS_URL API_KEY SECRET_KEY GITHUB_TOKEN GITHUB_ORG; do
    current="$(get_current_env "$name")"
    if [[ -z "$current" ]]; then
      continue
    fi

    case "$name" in
      REDIS_URL)
        if [[ -z "${REDIS_URL:-}" || "${REDIS_URL:-}" == redis://localhost* ]]; then
          export REDIS_URL="$current"
        fi
        ;;
      API_KEY)
        if [[ -z "${API_KEY:-}" || "${API_KEY:-}" == swarm-factory-dev-key ]]; then
          export API_KEY="$current"
        fi
        ;;
      SECRET_KEY)
        if [[ -z "${SECRET_KEY:-}" || "${SECRET_KEY:-}" == change-this-* ]]; then
          export SECRET_KEY="$current"
        fi
        ;;
      *)
        if [[ -z "${!name:-}" ]]; then
          export "$name=$current"
        fi
        ;;
    esac
  done
}

hydrate_from_azure

ACR_NAME="${ACR_NAME:-${AZURE_CONTAINER_REGISTRY%%.*}}"
API_KEY="$(trim_trailing_space "${API_KEY:-}")"
VITE_API_KEY="$(trim_trailing_space "${VITE_API_KEY:-$API_KEY}")"
TAG="${TAG:-$(git rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)}"
IMAGE="${IMAGE:-${AZURE_CONTAINER_REGISTRY}/${IMAGE_REPOSITORY}:${TAG}}"

require_var API_KEY
require_var SECRET_KEY
require_var REDIS_URL
require_var AZURE_OPENAI_ENDPOINT
require_var AZURE_OPENAI_API_KEY

if [[ "$SKIP_BUILD" != "1" ]]; then
  require_cmd docker
  if [[ -z "${DOCKER_CONFIG:-}" ]]; then
    TEMP_DOCKER_CONFIG="$(mktemp -d /tmp/swarm-factory-docker-config.XXXXXX)"
    export DOCKER_CONFIG="$TEMP_DOCKER_CONFIG"
    printf '{"auths":{}}\n' > "${DOCKER_CONFIG}/config.json"
  fi

  info "Logging in to ACR: $ACR_NAME"
  az acr login --name "$ACR_NAME" >/dev/null

  info "Building image: $IMAGE"
  docker build \
    --file "$DOCKERFILE" \
    --build-arg VITE_API_KEY="$VITE_API_KEY" \
    --tag "$IMAGE" \
    .

  info "Pushing image: $IMAGE"
  docker push "$IMAGE"
else
  info "Skipping build/push; deploying existing image: $IMAGE"
fi

COMMON_ENV_VARS=(
  "AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
  "AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}"
  "AZURE_OPENAI_API_VERSION=${AZURE_OPENAI_API_VERSION:-2024-02-01}"
  "AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT:-gpt-4o}"
  "AZURE_OPENAI_DEPLOYMENT_GPT4O=${AZURE_OPENAI_DEPLOYMENT_GPT4O:-gpt-4o}"
  "AZURE_OPENAI_DEPLOYMENT_PHI4=${AZURE_OPENAI_DEPLOYMENT_PHI4:-phi-4}"
  "AZURE_OPENAI_DEPLOYMENT_MINI=${AZURE_OPENAI_DEPLOYMENT_MINI:-gpt-4o-mini}"
  "AZURE_SEARCH_ENDPOINT=${AZURE_SEARCH_ENDPOINT:-}"
  "AZURE_SEARCH_API_KEY=${AZURE_SEARCH_API_KEY:-}"
  "AZURE_SEARCH_INDEX_NAME=${AZURE_SEARCH_INDEX_NAME:-swarm-memory}"
  "REDIS_URL=${REDIS_URL}"
  "REDIS_SSL_CERT_REQS=${REDIS_SSL_CERT_REQS:-required}"
  "API_KEY=${API_KEY}"
  "SECRET_KEY=${SECRET_KEY}"
  "APP_ENV=production"
  "LOG_LEVEL=${LOG_LEVEL:-INFO}"
  "MAX_CONCURRENT_JOBS=${MAX_CONCURRENT_JOBS:-5}"
  "JOB_TIMEOUT_SECONDS=${JOB_TIMEOUT_SECONDS:-600}"
  "SESSION_STORE_PATH=${SESSION_STORE_PATH:-./sessions}"
  "PYTHONPATH=/app/backend"
  "GITHUB_TOKEN=${GITHUB_TOKEN:-}"
  "GITHUB_ORG=${GITHUB_ORG:-}"
)

wait_for_ready() {
  local app_name="$1"
  info "Waiting for latest revision to become ready: $app_name"
  for _ in $(seq 1 30); do
    latest_revision="$(az containerapp show --name "$app_name" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestRevisionName -o tsv)"
    ready_revision="$(az containerapp show --name "$app_name" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestReadyRevisionName -o tsv)"
    if [[ -n "$latest_revision" && "$latest_revision" == "$ready_revision" ]]; then
      success "Ready revision for $app_name: $ready_revision"
      return
    fi
    sleep 10
  done
  error "Timed out waiting for $app_name to become ready"
}

info "Deploying to Container App: $AZURE_CONTAINER_APP_NAME"
if az containerapp show --name "$AZURE_CONTAINER_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  az containerapp update \
    --name "$AZURE_CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$IMAGE" \
    --set-env-vars "${COMMON_ENV_VARS[@]}" \
    --output none
else
  az containerapp create \
    --name "$AZURE_CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --environment "$AZURE_CONTAINER_APP_ENV" \
    --image "$IMAGE" \
    --target-port 8000 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 5 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --env-vars "${COMMON_ENV_VARS[@]}" \
    --output none
fi

wait_for_ready "$AZURE_CONTAINER_APP_NAME"

if [[ "$DEPLOY_WORKER" == "1" ]]; then
  WORKER_ARGS=(
    "-A" "backend.celery_app"
    "worker"
    "--loglevel=${LOG_LEVEL:-INFO}"
    "--concurrency=${CELERY_CONCURRENCY}"
  )

  info "Deploying Celery worker Container App: $AZURE_WORKER_APP_NAME"
  if az containerapp show --name "$AZURE_WORKER_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
    az containerapp update \
      --name "$AZURE_WORKER_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --image "$IMAGE" \
      --command "celery" \
      --args "${WORKER_ARGS[@]}" \
      --set-env-vars "${COMMON_ENV_VARS[@]}" \
      --output none
  else
    az containerapp create \
      --name "$AZURE_WORKER_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --environment "$AZURE_CONTAINER_APP_ENV" \
      --image "$IMAGE" \
      --min-replicas 1 \
      --max-replicas 3 \
      --cpu 1.0 \
      --memory 2.0Gi \
      --command "celery" \
      --args "${WORKER_ARGS[@]}" \
      --env-vars "${COMMON_ENV_VARS[@]}" \
      --output none
  fi

  wait_for_ready "$AZURE_WORKER_APP_NAME"
else
  warn "Skipping Celery worker deployment because DEPLOY_WORKER=$DEPLOY_WORKER"
fi

FQDN="$(az containerapp show --name "$AZURE_CONTAINER_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"
[[ -n "$FQDN" ]] || error "Could not resolve Container App FQDN"

info "Verifying live app..."
curl --fail --max-time 30 --retry 5 --retry-delay 5 "https://${FQDN}/health" >/dev/null
status_code="$(curl --silent --show-error --max-time 30 --retry 5 --retry-delay 5 \
  -H "X-API-Key: ${API_KEY}" \
  -o /tmp/swarm-factory-deploy-check.json \
  -w '%{http_code}' \
  "https://${FQDN}/api/status/deploy-check")"
if [[ "$status_code" != "404" ]] || ! grep -q 'job_not_found' /tmp/swarm-factory-deploy-check.json 2>/dev/null; then
  cat /tmp/swarm-factory-deploy-check.json 2>/dev/null || true
  error "Protected API verification failed with HTTP ${status_code}"
fi

success "Deployment complete"
echo ""
echo "  Image:  $IMAGE"
echo "  URL:    https://${FQDN}"
echo "  Health: https://${FQDN}/health"
echo ""
