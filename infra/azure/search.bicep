// =============================================================
// Swarm Factory — Azure AI Search Bicep Template
// =============================================================

@description('Name of the Azure AI Search service')
param searchServiceName string = 'swarm-factory-search'

@description('Location for the search service')
param location string = resourceGroup().location

@description('SKU for the search service')
@allowed(['free', 'basic', 'standard'])
param sku string = 'basic'

resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  sku: {
    name: sku
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    networkRuleSet: {
      ipRules: []
    }
    encryptionWithCmk: {
      enforcement: 'Unspecified'
    }
    semanticSearch: 'free'
  }
}

output searchServiceEndpoint string = 'https://${searchService.name}.search.windows.net'
output searchServiceName string = searchService.name
