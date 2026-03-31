<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { searchParticipants } from '@/api/delegations'
import type { Participant } from '@/types'
import BaseButton from '@/components/ui/BaseButton.vue'
import { getErrorMessage } from '@/utils/errors'

const router = useRouter()
const auth = useAuthStore()

const participants = ref<Participant[]>([])
const selectedParty = ref('')
const loading = ref(false)
const error = ref('')

// Load participants on mount
;(async () => {
  try {
    const res = await searchParticipants('')
    participants.value = res.items.filter(
      (participant) => participant.dsgoRoles.includes('ServiceConsumer'),
    )
    if (participants.value.length) selectedParty.value = participants.value[0].partyId
  } catch (err) {
    error.value = getErrorMessage(err, 'Participantenregister kon niet worden geladen.')
  }
})()

async function simulate() {
  if (!selectedParty.value) return
  loading.value = true
  error.value = ''
  try {
    await auth.simulateConsumer(selectedParty.value)
    router.push('/consumer/projects')
  } catch (err) {
    error.value = getErrorMessage(err, 'Consumer-simulatie kon niet worden gestart.')
  } finally {
    loading.value = false
  }
}

const selectedParticipant = computed(
  () => participants.value.find((participant) => participant.partyId === selectedParty.value) ?? null,
)
</script>

<template>
  <div class="min-h-screen bg-background flex items-center justify-center">
    <div class="bg-surface rounded-xl border border-border shadow-lg shadow-black/[0.04] p-10 w-[520px] flex flex-col items-center gap-7">
      <div class="flex items-center gap-3">
        <img src="/logos/vondr.png" alt="Vondr" class="h-6" />
        <img src="/logos/digigo.webp" alt="DigiGO" class="h-6 rounded" />
      </div>

      <div class="text-center">
        <h1 class="text-xl font-semibold text-text">Consumer perspectief</h1>
        <p class="text-sm text-text-muted mt-1">Bekijk het project vanuit een gesimuleerde organisatie.</p>
      </div>

      <div class="w-full bg-warning-light border border-amber-200 rounded-lg p-3 flex items-start gap-2">
        <svg class="w-4 h-4 text-warning mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
        <div>
          <p class="text-sm font-medium text-amber-800">Playground & simulatie</p>
          <p class="text-xs text-amber-700 mt-0.5">In productie authenticeert een consumer met een eigen iSHARE-certificaat via het DSGO. De provider kan alleen demonstreren hoe dit eruitziet: zij kan een organisatie selecteren uit het Participantenregister en vervolgens als ServiceConsumer het platform bekijken.</p>
        </div>
      </div>

      <p v-if="error" class="w-full text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3">{{ error }}</p>

      <div class="w-full flex flex-col gap-2">
        <p class="text-sm font-medium">Bekijk als</p>
        <select
          v-model="selectedParty"
          class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-consumer/30 focus:border-consumer"
          :disabled="!participants.length"
        >
          <option v-for="p in participants" :key="p.partyId" :value="p.partyId">{{ p.name }}</option>
        </select>
        <div v-if="selectedParticipant" class="flex flex-col gap-1 text-xs text-text-muted">
          <div class="flex items-center gap-1">
            <span class="w-2 h-2 rounded-full bg-consumer" />
            Gevonden in DSGO Participantenregister
          </div>
          <div class="flex items-center gap-1">
            <span class="w-2 h-2 rounded-full bg-consumer" />
            Rol: {{ selectedParticipant.dsgoRoles.join(', ') }} · Status: {{ selectedParticipant.membershipStatus }}
          </div>
          <div class="flex items-center gap-1">
            <span class="w-2 h-2 rounded-full bg-consumer" />
            Party ID: {{ selectedParticipant.partyId }}
          </div>
        </div>
        <p v-else class="text-xs text-text-muted">Geen andere ServiceConsumer beschikbaar in het mock participantenregister.</p>
      </div>

      <BaseButton variant="consumer" size="lg" class="w-full" :loading="loading" :disabled="!selectedParty" @click="simulate">
        Bekijk als consumer
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
      </BaseButton>
    </div>
  </div>
</template>
