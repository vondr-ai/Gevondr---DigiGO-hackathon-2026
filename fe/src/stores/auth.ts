import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User } from '@/types'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(localStorage.getItem('token'))
  const providerToken = ref<string | null>(localStorage.getItem('providerToken'))

  const isAuthenticated = computed(() => !!token.value)
  const isProvider = computed(() => user.value?.actorType === 'provider')
  const isConsumer = computed(() => user.value?.actorType === 'consumer')
  const canExitConsumer = computed(() => isConsumer.value && !!providerToken.value)

  async function providerLogin() {
    const res = await authApi.providerLogin()
    token.value = res.token
    user.value = res.user
    localStorage.setItem('token', res.token)
    providerToken.value = res.token
    localStorage.setItem('providerToken', res.token)
  }

  async function checkSession() {
    if (!token.value) return false
    try {
      const res = await authApi.getSession()
      user.value = res.user
      return true
    } catch {
      token.value = null
      localStorage.removeItem('token')
      return false
    }
  }

  async function simulateConsumer(consumerPartyId: string) {
    // Save provider token before switching
    if (isProvider.value && token.value) {
      providerToken.value = token.value
      localStorage.setItem('providerToken', token.value)
    }
    const res = await authApi.simulateConsumer(consumerPartyId)
    token.value = res.token
    user.value = res.user
    localStorage.setItem('token', res.token)
  }

  async function exitConsumer() {
    if (!providerToken.value) return
    token.value = providerToken.value
    localStorage.setItem('token', providerToken.value)
    // Re-check session to get provider user object
    await checkSession()
  }

  async function logout() {
    await authApi.logout()
    token.value = null
    user.value = null
    providerToken.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('providerToken')
  }

  return { user, token, isAuthenticated, isProvider, isConsumer, canExitConsumer, providerLogin, checkSession, simulateConsumer, exitConsumer, logout }
})
