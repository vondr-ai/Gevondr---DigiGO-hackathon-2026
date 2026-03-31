<script setup lang="ts">
import axios from 'axios'
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { getIndexingJob, getIndexingSummary, getLatestIndexingJob, startIndexing } from '@/api/indexing'
import type { IndexingJob, IndexingSummary } from '@/types'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import { getErrorMessage } from '@/utils/errors'

const { prevStep, projectId } = useStepNavigation()
const router = useRouter()

const summary = ref<IndexingSummary | null>(null)
const indexing = ref(false)
const done = ref(false)
const job = ref<IndexingJob | null>(null)
const error = ref('')
const reconnectNotice = ref('')

let pollRunId = 0

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isJobInProgress(status?: IndexingJob['status']) {
  return status === 'queued' || status === 'running'
}

function applyJobState(nextJob: IndexingJob | null) {
  job.value = nextJob
  indexing.value = Boolean(nextJob && isJobInProgress(nextJob.status))
  done.value = nextJob?.status === 'completed'

  if (nextJob?.status === 'completed') {
    error.value = ''
    reconnectNotice.value = ''
    return
  }

  if (nextJob?.status === 'failed') {
    error.value = nextJob.errorMessage || 'De indexering is in de backend mislukt.'
    reconnectNotice.value = ''
  }
}

async function loadSummary() {
  summary.value = await getIndexingSummary(projectId.value)
}

async function pollJob(jobId: string) {
  const currentRunId = ++pollRunId

  while (currentRunId === pollRunId) {
    try {
      const latestJob = await getIndexingJob(projectId.value, jobId)
      applyJobState(latestJob)

      if (latestJob.status === 'completed') {
        await loadSummary()
        return
      }

      if (latestJob.status === 'failed') {
        return
      }

      if (error.value === 'Verbinding met de indexering verloren. We proberen opnieuw.') {
        error.value = ''
      }
    } catch {
      if (currentRunId !== pollRunId) return
      error.value = 'Verbinding met de indexering verloren. We proberen opnieuw.'
    }

    await sleep(1500)
  }
}

async function resumeLatestJob() {
  try {
    const latestJob = await getLatestIndexingJob(projectId.value)
    applyJobState(latestJob)

    if (isJobInProgress(latestJob.status)) {
      reconnectNotice.value = 'Lopende indexering opnieuw gekoppeld. De voortgang wordt automatisch ververst.'
      void pollJob(latestJob.jobId)
    }
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return
    }

    error.value = getErrorMessage(err, 'Lopende indexering kon niet worden opgehaald.')
  }
}

onMounted(async () => {
  try {
    await loadSummary()
    await resumeLatestJob()
  } catch (err) {
    error.value = getErrorMessage(err, 'Indexing-overzicht kon niet worden geladen.')
  }
})

onUnmounted(() => {
  pollRunId += 1
})

async function handleIndex() {
  if (!summary.value?.readyToStart) return

  error.value = ''
  reconnectNotice.value = ''
  try {
    const started = await startIndexing(projectId.value)
    applyJobState(started)

    if (started.status === 'completed') {
      await loadSummary()
      return
    }

    if (isJobInProgress(started.status)) {
      void pollJob(started.jobId)
    }
  } catch (err) {
    error.value = getErrorMessage(err, 'Indexering starten is mislukt.')
  }
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <h1 class="text-2xl font-semibold">Overzicht</h1>
    <p class="text-sm text-text-secondary">Controleer je instellingen voordat je de indexering start.</p>
  </div>

  <template v-if="summary">
    <div class="grid grid-cols-2 gap-4">
      <div class="border border-border rounded-lg p-4 flex flex-col gap-2">
        <p class="text-xs font-semibold text-text-muted uppercase tracking-wider">Databron</p>
        <div class="flex items-center gap-2">
          <svg class="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
          <span class="text-sm font-medium">{{ summary.datasources[0]?.displayName ?? 'Nog geen databron' }}</span>
        </div>
        <p class="text-xs text-text-muted">Type: {{ summary.datasources[0]?.type ?? 'n.v.t.' }}</p>
      </div>

      <!-- Classificatie -->
      <div class="border border-border rounded-lg p-4 flex flex-col gap-2">
        <p class="text-xs font-semibold text-text-muted uppercase tracking-wider">Classificatie</p>
        <div class="flex items-center gap-2">
          <svg class="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
          <span class="text-sm font-medium">NEN 2084 — 24 documenttypen</span>
        </div>
        <div class="flex items-center gap-2">
          <svg class="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
          <span class="text-sm font-medium">GEBORA — 17 waardestromen</span>
        </div>
        <p class="text-xs text-text-muted">Documenten worden automatisch geclassificeerd</p>
      </div>

      <div class="border border-border rounded-lg p-4 flex flex-col gap-2">
        <p class="text-xs font-semibold text-text-muted uppercase tracking-wider">Rollen &amp; organisaties</p>
        <p class="text-sm">{{ summary.delegations.count }} delegaties opgeslagen</p>
        <p class="text-xs text-text-muted">{{ summary.accessMatrix.count }} ACL-regels worden meegegeven aan de indexering</p>
      </div>

      <div class="border border-border rounded-lg p-4 flex flex-col gap-2">
        <p class="text-xs font-semibold text-text-muted uppercase tracking-wider">Prompt</p>
        <p class="text-sm text-text-secondary italic">
          "{{ summary.norms.instructions || 'Geen extra indexeringsinstructies opgegeven.' }}"
        </p>
      </div>
    </div>

    <div v-if="summary.warnings.length" class="bg-warning-light border border-amber-200 rounded-lg p-3">
      <p v-for="w in summary.warnings" :key="w" class="text-xs text-amber-700">{{ w }}</p>
    </div>

    <div v-if="job && !done" class="border border-border rounded-lg px-4 py-3 text-sm text-text-secondary">
      Status: {{ job.status }}
      <span v-if="job.progress || job.progress === 0"> &middot; {{ job.progress }}%</span>
      <span v-if="job.totalFiles"> &middot; {{ job.indexedFiles ?? 0 }}/{{ job.totalFiles }} documenten</span>
    </div>

    <div v-if="reconnectNotice" class="border border-blue-200 bg-blue-50 rounded-lg px-4 py-3 text-sm text-blue-700">
      {{ reconnectNotice }}
    </div>

    <div v-if="error" class="border border-red-200 bg-red-50 rounded-lg px-4 py-3 text-sm text-red-700">
      {{ error }}
    </div>

    <button
      v-if="!done"
      :disabled="indexing || !summary.readyToStart"
      class="w-full py-4 rounded-xl text-white font-semibold text-lg flex items-center justify-center gap-2 transition-all cursor-pointer"
      :class="indexing || !summary.readyToStart ? 'bg-primary/70' : 'bg-primary hover:bg-primary-hover shadow-lg shadow-primary/30'"
      @click="handleIndex"
    >
      <svg v-if="indexing" class="animate-spin h-5 w-5" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
      <span v-else>&#10022;</span>
      {{ indexing ? 'Indexering bezig...' : summary.readyToStart ? 'Start indexering' : 'Indexering nog niet klaar' }}
    </button>

    <div v-if="done" class="flex flex-col items-center gap-4 py-4">
      <BaseBadge variant="success" class="text-sm px-4 py-1.5">
        Indexering voltooid - {{ job?.indexedFiles ?? 0 }} documenten verwerkt
      </BaseBadge>
      <BaseButton variant="consumer" @click="router.push('/consumer/simulate')">
        Bekijk als consumer
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
      </BaseButton>
    </div>

    <div v-if="!done" class="flex justify-start">
      <BaseButton variant="ghost" @click="prevStep">
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 17l-5-5m0 0l5-5m-5 5h12"/></svg>
        Terug
      </BaseButton>
    </div>
  </template>
</template>
