<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectsStore } from '@/stores/projects'
import ProviderLayout from '@/components/layout/ProviderLayout.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseInput from '@/components/ui/BaseInput.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'

const store = useProjectsStore()
const router = useRouter()
const showCreate = ref(false)
const newName = ref('')
const deleting = ref<string | null>(null)

onMounted(() => store.fetchProjects())

async function remove(id: string, event: Event) {
  event.stopPropagation()
  deleting.value = id
  try {
    await store.deleteProject(id)
  } finally {
    deleting.value = null
  }
}

async function create() {
  const project = await store.createProject(newName.value)
  showCreate.value = false
  newName.value = ''
  router.push({ name: 'setup-datasource', params: { id: project.id } })
}

function openProject(id: string) {
  router.push({ name: 'setup-datasource', params: { id } })
}
</script>

<template>
  <ProviderLayout>
    <div class="flex flex-col gap-1 mb-6">
      <h1 class="text-2xl font-semibold">Projecten</h1>
      <p class="text-sm text-text-secondary">Beheer je projecten en deel gebouwinformatie via het DSGO.</p>
    </div>

    <div class="grid grid-cols-3 gap-5">
      <BaseCard v-for="p in store.items" :key="p.id" hover @click="openProject(p.id)">
        <div class="relative flex flex-col items-center gap-3 py-4">
          <button
            type="button"
            class="absolute top-2 right-2 p-1 rounded-md text-text-muted hover:text-red-600 hover:bg-red-50 transition-colors"
            title="Verwijderen"
            :disabled="deleting === p.id"
            @click="remove(p.id, $event)"
          >
            <svg v-if="deleting === p.id" class="w-4 h-4 animate-spin" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
          <div class="w-14 h-14 bg-background rounded-xl flex items-center justify-center">
            <svg class="w-7 h-7 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/></svg>
          </div>
          <div class="text-center">
            <p class="text-sm font-semibold text-text">{{ p.name }}</p>
            <p class="text-xs text-text-muted mt-1">{{ p.fileCount ?? 0 }} bestanden · {{ p.normCount ?? 0 }} normen</p>
          </div>
          <BaseBadge v-if="p.status === 'configured'" variant="success">Geconfigureerd</BaseBadge>
          <BaseBadge v-else variant="neutral">{{ p.status }}</BaseBadge>
        </div>
      </BaseCard>

      <BaseCard dashed hover @click="showCreate = true">
        <div class="flex flex-col items-center justify-center gap-2 py-8 text-text-muted">
          <svg class="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 4v16m8-8H4"/></svg>
          <p class="text-sm font-medium">Nieuw project</p>
          <p class="text-xs">Maak een nieuw project aan om databronnen te koppelen.</p>
        </div>
      </BaseCard>
    </div>

    <div class="mt-8 pt-6 border-t border-border">
      <BaseButton variant="consumer" @click="router.push('/consumer/simulate')">
        Consumer perspectief bekijken
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
      </BaseButton>
    </div>

    <BaseModal :open="showCreate" @close="showCreate = false">
      <div class="p-6 flex flex-col gap-4">
        <h2 class="text-lg font-semibold">Nieuw project</h2>
        <BaseInput v-model="newName" label="Projectnaam" placeholder="bijv. Hoogbouw Rivierenbuurt" />
        <div class="flex justify-end gap-2">
          <BaseButton variant="ghost" @click="showCreate = false">Annuleren</BaseButton>
          <BaseButton @click="create" :disabled="!newName">Aanmaken</BaseButton>
        </div>
      </div>
    </BaseModal>
  </ProviderLayout>
</template>
