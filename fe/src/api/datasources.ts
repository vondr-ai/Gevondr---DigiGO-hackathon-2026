import client from './client'
import type { Datasource, TreeNode, DiscoverJob } from '@/types'

type UploadableFile = File & {
  webkitRelativePath?: string
}

function normalizeDatasource(
  data: Partial<Datasource>,
  fallback: { type?: string; displayName?: string } = {},
): Datasource {
  return {
    id: data.id ?? '',
    type: data.type ?? fallback.type ?? 'upload',
    status: data.status ?? 'connected',
    displayName: data.displayName ?? fallback.displayName ?? 'Upload datasource',
    lastSyncAt: data.lastSyncAt,
    configMasked: data.configMasked,
  }
}

export async function listDatasources(projectId: string): Promise<{ items: Datasource[] }> {
  const { data } = await client.get<{ items: Datasource[] }>(`/projects/${projectId}/datasources`)
  return { items: data.items.map((item) => normalizeDatasource(item)) }
}

export async function createDatasource(projectId: string, body: { type: string; config?: Record<string, unknown> }): Promise<Datasource> {
  const fallbackDisplayName =
    typeof body.config?.displayName === 'string' ? body.config.displayName : undefined
  const { data } = await client.post<Datasource>(`/projects/${projectId}/datasources`, body)
  return normalizeDatasource(data, {
    type: body.type,
    displayName: fallbackDisplayName,
  })
}

export async function discoverDatasource(projectId: string, datasourceId: string, rootPath?: string): Promise<DiscoverJob> {
  const { data } = await client.post<DiscoverJob>(`/projects/${projectId}/datasources/${datasourceId}/discover`, { rootPath: rootPath ?? '/' })
  return data
}

export async function getTree(projectId: string, datasourceId: string): Promise<{ root: TreeNode }> {
  const { data } = await client.get<{ root: TreeNode }>(`/projects/${projectId}/datasources/${datasourceId}/tree`)
  return data
}

export async function getPrimaryDatasource(projectId: string): Promise<Datasource | null> {
  const { items } = await listDatasources(projectId)
  return items[0] ?? null
}

export async function uploadFiles(
  projectId: string,
  datasourceId: string,
  files: UploadableFile[],
  targetPath?: string,
): Promise<{ uploaded: { documentId: string; fileName: string; size: number; path: string }[] }> {
  const form = new FormData()
  files.forEach((file) => {
    const relativePath = file.webkitRelativePath || file.name
    form.append('files', file, file.name)
    form.append('relativePaths', relativePath)
  })
  if (targetPath) form.append('targetPath', targetPath)
  const { data } = await client.post(`/projects/${projectId}/datasources/${datasourceId}/uploads`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}
