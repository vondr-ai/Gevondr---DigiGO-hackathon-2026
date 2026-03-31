import client from './client'
import type { AiConfig } from '@/types'

export async function getAiConfig(projectId: string): Promise<AiConfig> {
  const { data } = await client.get<AiConfig>(`/projects/${projectId}/ai-config`)
  return data
}

export async function updateAiConfig(
  projectId: string,
  body: { provider: string; model: string; apiKey?: string; chunking: { size: number; overlap: number } },
): Promise<AiConfig> {
  const { data } = await client.put<AiConfig>(`/projects/${projectId}/ai-config`, body)
  return { ...data, chunking: body.chunking }
}
