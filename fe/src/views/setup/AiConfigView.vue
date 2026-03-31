<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { getAiConfig, updateAiConfig } from '@/api/ai-config'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseRadio from '@/components/ui/BaseRadio.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseModal from '@/components/ui/BaseModal.vue'

const { nextStep, prevStep, projectId } = useStepNavigation()

const selectedModel = ref('gemini-3-flash-preview')
const apiKey = ref('')
const showByom = ref(false)
const saving = ref(false)
const error = ref('')

const byomSelected = computed(() => selectedModel.value === 'custom')

onMounted(async () => {
  try {
    const config = await getAiConfig(projectId.value)
    if (config.model) selectedModel.value = config.model
    if (config.apiKeySet) apiKey.value = '••••••••••••'
  } catch { /* first time */ }
})

async function save() {
  if (byomSelected.value) {
    showByom.value = true
    return
  }

  saving.value = true
  error.value = ''
  try {
    await updateAiConfig(projectId.value, {
      provider: 'gemini',
      model: selectedModel.value,
      apiKey: apiKey.value.includes('••') ? undefined : apiKey.value,
      chunking: { size: 800, overlap: 120 },
    })
    nextStep()
  } catch (e: any) {
    error.value = e.response?.data?.error?.message ?? e.response?.data?.detail ?? 'AI-configuratie opslaan mislukt.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <h1 class="text-2xl font-semibold">AI configureren</h1>
    <p class="text-sm text-text-secondary">Kies een AI-model voor het indexeren van documenten.</p>
  </div>

  <div class="flex flex-col gap-2.5">
    <p class="text-sm font-medium text-text">Model</p>
    <BaseRadio v-model="selectedModel" value="gemini-3-flash-preview" label="Gemini 3 Flash Preview (Google)" description="Backend default · snelle multimodale verwerking">
      <BaseBadge variant="primary" class="mt-1">Standaard</BaseBadge>
    </BaseRadio>
    <BaseRadio v-model="selectedModel" value="gemini-2.5-pro" label="Gemini 2.5 Pro (Google)" description="1M context · geavanceerde redenering" />
    <BaseRadio v-model="selectedModel" value="custom" label="Eigen model (BYOM)" description="Breng je eigen Azure-deployed model mee">
      <button v-if="selectedModel === 'custom'" @click="showByom = true" class="text-xs text-primary hover:underline mt-1">Configureren →</button>
    </BaseRadio>
  </div>

  <p v-if="error" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3">{{ error }}</p>

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

  <BaseModal :open="showByom" @close="showByom = false">
    <div class="p-6 flex flex-col gap-4">
      <div class="flex justify-between items-center">
        <h2 class="text-lg font-semibold">Eigen model configureren (BYOM)</h2>
        <button @click="showByom = false" class="text-text-muted hover:text-text">&times;</button>
      </div>
      <BaseInput label="Azure Endpoint URL" placeholder="https://your-resource.openai.azure.com/" />
      <BaseInput label="API Key" type="password" placeholder="Plak hier je Azure API-key" />
      <BaseInput label="Deployment Name" placeholder="bijv. gpt-4o-deployment" />
      <BaseInput label="API Version" placeholder="bijv. 2024-02-15-preview" />
      <div class="flex justify-end gap-2">
        <BaseButton variant="ghost" @click="showByom = false">Annuleren</BaseButton>
        <BaseButton>Verbinding testen &amp; opslaan</BaseButton>
      </div>
    </div>
  </BaseModal>
</template>
