import client from './client'
import type { Participant, Delegation } from '@/types'

export async function searchParticipants(search: string): Promise<{ items: Participant[] }> {
  const { data } = await client.get<{ items: Participant[] }>('/delegations/participants', {
    params: { search: search || undefined, requiredDsgoRole: 'ServiceConsumer' },
  })
  return data
}

export async function getDelegations(projectId: string): Promise<{ items: Delegation[] }> {
  const { data } = await client.get<{ items: Delegation[] }>(`/projects/${projectId}/delegations`)
  return data
}

export async function updateDelegations(projectId: string, items: { roleCode: string; partyId: string }[]): Promise<{ items: Delegation[]; validation: { allParticipantsExist: boolean } }> {
  const { data } = await client.put(`/projects/${projectId}/delegations`, { items })
  return data
}
