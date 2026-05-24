// infra/azure/main.bicep
// ----------------------
// Top-level Bicep template for Swarm Factory Azure infrastructure.
// Provisions: Azure Container Registry, Container Apps Environment, and Bing Search.
//
// Deploy:
//   az deployment group create \
//     --resource-group swarm-factory-rg \
//     --template-file infra/azure/main.bicep \
//     --parameters @infra/azure/parameters.json

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Base name prefix for all resources (lowercase, no hyphens).')
param baseName string = 'swarmfactory'

@description('Container Apps Environment name.')
param containerAppEnvName string = '${baseName}-env'

@description('Azure Container Registry name (globally unique, lowercase, 5-50 chars).')
param acrName string = '${baseName}acr'

@description('SKU for Azure Container Registry.')
@allowed(['Basic', 'Standard', 'Premium'])
param acrSku string = 'Basic'

@description('Log Analytics workspace name for Container Apps diagnostics.')
param logAnalyticsName string = '${baseName}-logs'

// ── Log Analytics workspace ────────────────────────────────────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ── Azure Container Registry ───────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' = {
  name: acrName
  location: location
  sku: {
    name: acrSku
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
}

// ── Container Apps Environment ─────────────────────────────────────────────────
resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ── Bing Search (for DevOps agent web search) ──────────────────────────────────
resource bingSearch 'Microsoft.Bing/accounts@2020-06-10' = {
  name: '${baseName}-bing'
  location: 'global'
  sku: {
    name: 'S1'
  }
  kind: 'Bing.Search.v7'
}

// ── Outputs ────────────────────────────────────────────────────────────────────
output acrLoginServer string = acr.properties.loginServer
output containerAppEnvId string = containerAppEnv.id
output containerAppEnvName string = containerAppEnv.name
output logAnalyticsWorkspaceId string = logAnalytics.id
output bingSearchEndpoint string = 'https://api.bing.microsoft.com/'
