<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}

async function handleExitConsumer() {
  await auth.exitConsumer()
  router.push('/projects')
}
</script>

<template>
  <header class="flex items-center justify-between h-12 px-6 bg-surface border-b border-border">
    <div class="flex items-center gap-3">
      <img src="/logos/vondr.png" alt="Vondr" class="h-5" />
      <img src="/logos/digigo.webp" alt="DigiGO" class="h-5 rounded" />
    </div>
    <div class="flex items-center gap-4">
      <router-link
        v-if="auth.isProvider"
        to="/projects"
        class="text-sm text-text-secondary hover:text-text"
      >
        Projecten
      </router-link>
      <button
        v-if="auth.canExitConsumer"
        @click="handleExitConsumer"
        class="text-xs text-consumer hover:text-text transition-colors"
      >
        Terug naar provider
      </button>
      <span v-if="auth.isConsumer" class="text-xs font-medium text-consumer bg-consumer-light px-2 py-0.5 rounded-full">
        Consumer
      </span>
      <button
        v-if="auth.isAuthenticated"
        @click="handleLogout"
        class="w-8 h-8 rounded-full text-white text-sm font-semibold flex items-center justify-center"
        :class="auth.isConsumer ? 'bg-consumer' : 'bg-primary'"
      >
        {{ auth.user?.partyName?.charAt(0) ?? 'V' }}
      </button>
    </div>
  </header>
</template>
