import client from './client'
import type { Project } from '@/types'

export async function listProjects(): Promise<{ items: Project[] }> {
  const { data } = await client.get<{ items: Project[] }>('/projects')
  return data
}

export async function createProject(body: { name: string; description?: string }): Promise<Project> {
  const { data } = await client.post<Project>('/projects', { ...body, status: 'draft' })
  return data
}

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await client.get<Project>(`/projects/${projectId}`)
  return data
}

export async function patchProject(projectId: string, body: { name?: string; description?: string; status?: string }): Promise<Project> {
  const { data } = await client.patch<Project>(`/projects/${projectId}`, body)
  return data
}

export async function deleteProject(projectId: string): Promise<void> {
  await client.delete(`/projects/${projectId}`)
}

export async function listConsumerProjects(): Promise<{ items: Project[] }> {
  const { data } = await client.get<{ items: Project[] }>('/consumer/projects')
  return data
}
