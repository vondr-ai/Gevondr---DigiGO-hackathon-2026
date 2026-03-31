<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { listDatasources, createDatasource, uploadFiles } from '@/api/datasources'
import type { Datasource } from '@/types'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import { getErrorMessage } from '@/utils/errors'

const { nextStep, projectId } = useStepNavigation()

const sources = [
  { type: 'upload', name: 'Upload', icon: null },
  { type: 'sharepoint', name: 'SharePoint', icon: '/logos/sharepoint.png' },
  { type: 'relatics', name: 'Relatics', icon: '/logos/relatics.png' },
  { type: 'autodesk-cc', name: 'Autodesk CC', icon: '/logos/autodesk.png' },
  { type: 'thinkproject', name: 'ThinkProject', icon: '/logos/thinkproject.jpg' },
  { type: 'primavera', name: 'Primavera P6', icon: '/logos/primavera.png' },
  { type: 'maximo', name: 'IBM Maximo', icon: '/logos/maximo.webp' },
  { type: 'ultimo', name: 'Ultimo', icon: '/logos/ultimo.png' },
  { type: '4ps', name: '4PS', icon: '/logos/4ps.webp' },
]

const selected = ref('upload')
const existingDatasources = ref<Datasource[]>([])
const creating = ref(false)
const uploading = ref(false)
const folderInput = ref<HTMLInputElement | null>(null)
const currentDatasourceId = ref<string | null>(null)
const error = ref('')

function findExistingDatasource(type: string) {
  return existingDatasources.value.find((datasource) => datasource.type === type) ?? null
}

function selectSource(type: string) {
  selected.value = type
  currentDatasourceId.value = findExistingDatasource(type)?.id ?? null
}

onMounted(async () => {
  try {
    const res = await listDatasources(projectId.value)
    existingDatasources.value = res.items
    if (res.items.length > 0) {
      currentDatasourceId.value = res.items[0].id
      selected.value = res.items[0].type
    }
  } catch (err) {
    error.value = getErrorMessage(err, 'Databronnen konden niet worden geladen.')
  }
})

async function ensureDatasource() {
  error.value = ''
  const existing = findExistingDatasource(selected.value)
  if (existing) {
    currentDatasourceId.value = existing.id
  }

  if (!currentDatasourceId.value) {
    creating.value = true
    try {
      const ds = await createDatasource(projectId.value, {
        type: selected.value,
        config: { displayName: 'Upload datasource' },
      })
      currentDatasourceId.value = ds.id
      existingDatasources.value.push(ds)
    } catch (err) {
      error.value = getErrorMessage(err, 'Databron kon niet worden aangemaakt.')
      return
    } finally {
      creating.value = false
    }
  }
}

function openFolderPicker() {
  folderInput.value?.click()
}

async function startUploadFlow() {
  await ensureDatasource()
  if (!currentDatasourceId.value) return
  openFolderPicker()
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length || !currentDatasourceId.value) return

  uploading.value = true
  error.value = ''
  try {
    const files = Array.from(input.files)
    await uploadFiles(projectId.value, currentDatasourceId.value, files)
    nextStep()
  } catch (err) {
    error.value = getErrorMessage(err, 'Bestanden uploaden is mislukt.')
  } finally {
    uploading.value = false
    input.value = ''
  }
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <h1 class="text-2xl font-semibold">Databron koppelen</h1>
    <p class="text-sm text-text-secondary">Waar staan je documenten? Koppel een databron om te beginnen.</p>
  </div>

  <div class="grid grid-cols-4 gap-4">
    <BaseCard
      v-for="s in sources"
      :key="s.type"
      hover
      :selected="selected === s.type"
      @click="selectSource(s.type)"
    >
      <div class="flex flex-col items-center gap-3 py-6">
        <img v-if="s.icon" :src="s.icon" :alt="s.name" class="h-14 w-14 object-contain" />
        <div v-else class="w-14 h-14 bg-background rounded-xl flex items-center justify-center">
          <svg class="w-7 h-7 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
        </div>
        <p class="text-sm font-medium">{{ s.name }}</p>
      </div>
    </BaseCard>
  </div>

  <p v-if="error" class="border border-red-200 bg-red-50 rounded-lg px-4 py-3 text-sm text-red-700">
    {{ error }}
  </p>

  <input ref="folderInput" type="file" multiple class="hidden" webkitdirectory directory @change="handleUpload" />

  <div class="flex justify-end">
    <BaseButton @click="startUploadFlow" :loading="creating || uploading" :disabled="selected !== 'upload'">
      {{ currentDatasourceId ? 'Map uploaden' : 'Databron aanmaken & map uploaden' }}
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
    </BaseButton>
  </div>
</template>
