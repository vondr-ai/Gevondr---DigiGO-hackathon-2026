import client from './client'
import type { AuthResponse, User } from '@/types'

export async function providerLogin(): Promise<AuthResponse> {
  const { data } = await client.post<AuthResponse>('/auth/provider/login', {})
  return data
}

export async function getSession(): Promise<{ user: User }> {
  const { data } = await client.get<{ user: User }>('/auth/session')
  return data
}

export async function simulateConsumer(consumerPartyId: string): Promise<AuthResponse> {
  const { data } = await client.post<AuthResponse>('/auth/consumer/simulate', { consumerPartyId })
  return data
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout', {})
}
