import client from './client'
import type { GeboraRole, AccessEntry } from '@/types'

export async function getGeboraRoles(): Promise<{ items: GeboraRole[] }> {
  const { data } = await client.get<{ items: GeboraRole[] }>('/roles/gebora')
  return data
}

export async function getAccessMatrix(projectId: string): Promise<{ entries: AccessEntry[] }> {
  const { data } = await client.get<{ entries: AccessEntry[] }>(`/projects/${projectId}/roles/access-matrix`)
  return data
}

export async function updateAccessMatrix(projectId: string, entries: AccessEntry[]): Promise<{ updatedCount: number; documentAclVersion: string }> {
  const payload = entries.map((entry) => ({
    roleCode: entry.roleCode,
    resourceType: entry.resourceType,
    resourceId: entry.resourceId,
    path: entry.path,
    allowRead: entry.allowRead,
  }))
  const { data } = await client.put(`/projects/${projectId}/roles/access-matrix`, { entries: payload })
  return data
}
