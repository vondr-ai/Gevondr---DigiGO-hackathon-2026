export interface User {
  actorType: 'provider' | 'consumer'
  partyId: string
  partyName: string
  certificateStatus?: string
  simulation?: boolean
  dsgoRoles: string[]
}

export interface AuthResponse {
  token: string
  user: User
}

export interface Project {
  id: string
  name: string
  description?: string
  status: string
  ownerPartyId?: string
  fileCount?: number
  normCount?: number
  datasourceCount?: number
  lastIndexedAt?: string
  // consumer fields
  resolvedRole?: string
  accessibleFileCount?: number
}

export interface Datasource {
  id: string
  type: string
  status: string
  displayName: string
  lastSyncAt?: string
  configMasked?: Record<string, unknown>
}

export interface TreeNode {
  id: string
  path: string
  type: 'folder' | 'file'
  name?: string
  size?: number
  children?: TreeNode[]
}

export interface AiConfig {
  provider: string
  model: string
  apiKeySet: boolean
  chunking?: { size: number; overlap: number }
  updatedAt?: string
}

export interface Norm {
  code: string
  label: string
  category: string
}

export interface GeboraRole {
  code: string
  label: string
  description: string
}

export interface AccessEntry {
  roleCode: string
  resourceType: 'folder' | 'file'
  resourceId: string
  path: string
  allowRead: boolean
  inherited: boolean
}

export interface Participant {
  partyId: string
  name: string
  membershipStatus: string
  dsgoRoles: string[]
}

export interface Delegation {
  roleCode: string
  partyId: string
  partyName: string
}

export interface IndexingSummary {
  project: Project
  datasources: Datasource[]
  norms: { selectedNorms: string[]; instructions?: string | null }
  delegations: { count: number }
  accessMatrix: { count: number }
  readyToStart: boolean
  warnings: string[]
}

export interface IndexingJob {
  jobId: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress?: number
  totalFiles?: number
  indexedFiles?: number
  failedFiles?: number
  startedAt?: string
  finishedAt?: string
  errorMessage?: string | null
}

export interface ProjectChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ProjectChatToolEvent {
  tool: 'search_project'
  phase: 'started' | 'completed'
  uniqueDocumentCount?: number
}

export interface ProjectChatRetrievalEvent {
  phase: 'started' | 'progress' | 'completed'
  queryCount: number
  completedQueries?: number
  sourcesUsed: number
}

export interface DocumentType {
  code: string
  label: string
  category: string
}

export interface ValueStream {
  code: string
  label: string
  description: string
}

export interface DiscoverJob {
  jobId: string
  status: 'discovering' | 'completed' | 'failed'
}

export interface ProjectChatUsage {
  requests: number
  inputTokens: number
  outputTokens: number
}
