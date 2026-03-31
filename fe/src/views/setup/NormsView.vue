<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { getDocumentTypesCatalog, getValueStreamsCatalog, updateProjectNorms } from '@/api/norms'
import type { DocumentType, ValueStream } from '@/types'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseCheckbox from '@/components/ui/BaseCheckbox.vue'

const { nextStep, prevStep, projectId } = useStepNavigation()

const documentTypes = ref<DocumentType[]>([])
const valueStreams = ref<ValueStream[]>([])
const nenEnabled = ref(true)
const geboraEnabled = ref(true)
const nenOpen = ref(false)
const geboraOpen = ref(false)
const instructions = ref('Classificeer alle documenten op constructieve veiligheid en brandveiligheid. Let extra op fundering en draagconstructies. Markeer alle verwijzingen naar normen en certificeringen.')
const saving = ref(false)

const groupedTypes = computed(() => {
  const groups: Record<string, DocumentType[]> = {}
  for (const dt of documentTypes.value) {
    ;(groups[dt.category] ??= []).push(dt)
  }
  return groups
})

onMounted(async () => {
  const [dtRes, vsRes] = await Promise.all([
    getDocumentTypesCatalog(),
    getValueStreamsCatalog(),
  ])
  documentTypes.value = dtRes.items
  valueStreams.value = vsRes.items
})

async function save() {
  saving.value = true
  try {
    const norms: string[] = []
    if (nenEnabled.value) norms.push('NEN 2084')
    if (geboraEnabled.value) norms.push('GEBORA')
    await updateProjectNorms(projectId.value, {
      selectedNorms: norms,
      indexingInstructions: instructions.value,
    })
    nextStep()
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <h1 class="text-2xl font-semibold">Classificatie & indexering</h1>
    <p class="text-sm text-text-secondary">Selecteer de classificatiestandaarden voor dit project.</p>
  </div>

  <!-- NEN 2084 -->
  <div class="flex flex-col gap-2">
    <div class="flex items-center justify-between">
      <button
        type="button"
        class="flex items-center gap-2 text-left"
        @click="nenOpen = !nenOpen"
      >
        <svg
          class="w-4 h-4 text-text-muted transition-transform duration-200"
          :class="nenOpen ? 'rotate-90' : ''"
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
        <span class="text-sm font-medium text-text">NEN 2084 — Documenttypen</span>
        <span class="flex items-center justify-center w-4 h-4 rounded-full bg-text-muted/15 text-text-muted text-[10px] font-semibold leading-none" title="NEN 2084 definieert een taxonomie van documenttypen. Elk document wordt automatisch geclassificeerd in exact 1 type.">i</span>
      </button>
      <BaseCheckbox :model-value="nenEnabled" @update:model-value="nenEnabled = $event" />
    </div>
    <p class="text-xs text-text-muted ml-6">Elk document wordt automatisch geclassificeerd in exact 1 documenttype.</p>

    <div v-if="nenOpen" class="flex flex-col gap-3 ml-6 mt-1">
      <div v-for="(types, category) in groupedTypes" :key="category" class="border border-border rounded-lg px-4 py-3">
        <p class="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">{{ category }}</p>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="dt in types"
            :key="dt.code"
            class="inline-flex items-center rounded-md bg-primary/8 px-2.5 py-1 text-xs font-medium text-primary"
          >
            {{ dt.label }}
          </span>
        </div>
      </div>
    </div>
  </div>

  <!-- GEBORA -->
  <div class="flex flex-col gap-2">
    <div class="flex items-center justify-between">
      <button
        type="button"
        class="flex items-center gap-2 text-left"
        @click="geboraOpen = !geboraOpen"
      >
        <svg
          class="w-4 h-4 text-text-muted transition-transform duration-200"
          :class="geboraOpen ? 'rotate-90' : ''"
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
        <span class="text-sm font-medium text-text">GEBORA — Waardestromen</span>
        <span class="flex items-center justify-center w-4 h-4 rounded-full bg-text-muted/15 text-text-muted text-[10px] font-semibold leading-none" title="GEBORA waardestromen beschrijven de procescontext van de gebouwde omgeving. Elk document wordt gekoppeld aan 1-3 relevante waardestromen.">i</span>
      </button>
      <BaseCheckbox :model-value="geboraEnabled" @update:model-value="geboraEnabled = $event" />
    </div>
    <p class="text-xs text-text-muted ml-6">Elk document wordt gekoppeld aan 1-3 relevante waardestromen.</p>

    <div v-if="geboraOpen" class="border border-border rounded-lg divide-y divide-border ml-6 mt-1">
      <div
        v-for="vs in valueStreams"
        :key="vs.code"
        class="flex items-start gap-3 px-4 py-2.5"
      >
        <span class="text-xs font-mono text-text-muted w-5 shrink-0 pt-0.5 text-right">{{ vs.code }}</span>
        <div class="flex flex-col">
          <span class="text-sm font-medium text-text">{{ vs.label }}</span>
          <span class="text-xs text-text-muted">{{ vs.description }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Indexeringsinstructies -->
  <div class="flex flex-col gap-2.5">
    <p class="text-sm font-medium text-text">Instructies voor indexering</p>
    <textarea
      v-model="instructions"
      rows="5"
      class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none"
      placeholder="Geef specifieke instructies voor hoe de AI de documenten moet analyseren..."
    />
  </div>

  <div class="flex justify-between">
    <BaseButton variant="ghost" @click="prevStep">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 17l-5-5m0 0l5-5m-5 5h12"/></svg>
      Terug
    </BaseButton>
    <BaseButton @click="save" :loading="saving">
      Volgende
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
    </BaseButton>
  </div>
</template>
