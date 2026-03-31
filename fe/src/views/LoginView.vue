<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import { getErrorMessage } from '@/utils/errors'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const error = ref('')

onMounted(async () => {
  if (auth.token) {
    const ok = await auth.checkSession()
    if (ok) {
      if (auth.isConsumer) {
        router.push('/consumer/projects')
      } else {
        router.push('/projects')
      }
    }
  }
})

async function login() {
  loading.value = true
  error.value = ''
  try {
    await auth.providerLogin()
    router.push('/projects')
  } catch (e: any) {
    error.value = getErrorMessage(e, 'Verbinding met backend mislukt. Draait de server op :8000?')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-background flex items-center justify-center">
    <div class="bg-surface rounded-xl border border-border shadow-lg shadow-black/[0.04] p-10 w-[440px] flex flex-col items-center gap-7">
      <div class="flex items-center gap-3">
        <img src="/logos/vondr.png" alt="Vondr" class="h-6" />
        <img src="/logos/digigo.webp" alt="DigiGO" class="h-6 rounded" />
      </div>

      <div class="text-center">
        <h1 class="text-xl font-semibold text-text">Demo-omgeving</h1>
        <p class="text-sm text-text-muted mt-1">DSGO Hackathon 2026</p>
      </div>

      <div class="w-full flex flex-col gap-3">
        <BaseBadge variant="success" class="self-start">
          <svg class="w-3.5 h-3.5 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
          iSHARE-certificaat geladen
        </BaseBadge>

        <div class="border border-border rounded-lg p-4">
          <p class="text-sm font-medium text-text">Vondr B.V.</p>
          <p class="text-xs text-text-muted mt-1">did:ishare:EU.NL.NTRNL-98499327</p>
          <p class="text-xs text-text-muted">DSGO rollen: ServiceProvider, ServiceConsumer · Active</p>
        </div>
      </div>

      <p v-if="error" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3 w-full">{{ error }}</p>

      <BaseButton size="lg" class="w-full" @click="login" :loading="loading">
        Open dashboard
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
      </BaseButton>
    </div>
  </div>
</template>
