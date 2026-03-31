import client from './client'
import type { DocumentType, ValueStream } from '@/types'

export async function getDocumentTypesCatalog(): Promise<{ items: DocumentType[] }> {
  const { data } = await client.get<{ items: DocumentType[] }>('/document-types/nen2084')
  return data
}

export async function getValueStreamsCatalog(): Promise<{ items: ValueStream[] }> {
  const { data } = await client.get<{ items: ValueStream[] }>('/value-streams/gebora')
  return data
}

export async function updateProjectNorms(projectId: string, body: { selectedNorms: string[]; indexingInstructions: string }): Promise<{ selectedNorms: string[]; instructionsPreview: string }> {
  const { data } = await client.put(`/projects/${projectId}/norms`, body)
  return data
}
