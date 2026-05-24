// infra/azure/container-app.bicep
// ---------------------------------
// Azure Container Apps app definition for Swarm Factory.
// References the environment created by main.bicep.
//
// Deploy:
//   az deployment group create \
//     --resource-group swarm-factory-rg \
//     --template-file infra/azure/container-app.bicep \
//     --parameters @infra/azure/parameters.json

@description('Azure region.')
param location string = resourceGroup().location

@description('Container App name.')
param appName string = 'swarm-factory-api'

@description('Resource ID of the Container Apps Managed Environment.')
param containerAppEnvId string

@description('Full image URI including tag, e.g. myregistry.azurecr.io/swarm-factory-api:latest')
param imageUri string

@description('Azure Container Registry login server hostname.')
param acrLoginServer string

@description('ACR admin username for image pull.')
@secure()
param acrUsername string

@description('ACR admin password for image pull.')
@secure()
param acrPassword string

@description('Minimum number of replicas (0 = scale to zero).')
param minReplicas int = 1

@description('Maximum number of replicas.')
param maxReplicas int = 5

@description('CPU cores allocated to each replica.')
param cpu string = '0.5'

@description('Memory allocated to each replica.')
param memory string = '1Gi'

// Environment variables injected into the container at runtime.
// Secrets (API keys) must be added via az containerapp secret set separately.
param envVars array = []

// ── Container App ─────────────────────────────────────────────────────────────
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnvId
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
      ]
    }
    template: {
      containers: [
        {
          name: appName
          image: imageUri
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: envVars
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 15
              periodSeconds: 30
              timeoutSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

// ── Outputs ────────────────────────────────────────────────────────────────────
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output appUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
