import client from './client'
import type { IndexingSummary, IndexingJob } from '@/types'

export async function getIndexingSummary(projectId: string): Promise<IndexingSummary> {
  const { data } = await client.get<IndexingSummary>(`/projects/${projectId}/indexing/summary`)
  return data
}

export async function startIndexing(projectId: string): Promise<IndexingJob> {
  const { data } = await client.post<IndexingJob>(`/projects/${projectId}/indexing-jobs`, { mode: 'full', reindex: true })
  return data
}

export async function getLatestIndexingJob(projectId: string): Promise<IndexingJob> {
  const { data } = await client.get<IndexingJob>(`/projects/${projectId}/indexing-jobs/latest`)
  return data
}

export async function getIndexingJob(projectId: string, jobId: string): Promise<IndexingJob> {
  const { data } = await client.get<IndexingJob>(`/projects/${projectId}/indexing-jobs/${jobId}`)
  return data
}
