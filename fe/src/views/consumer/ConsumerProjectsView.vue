<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listConsumerProjects } from '@/api/projects'
import TopBar from '@/components/layout/TopBar.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import type { Project } from '@/types'

const router = useRouter()
const projects = ref<Project[]>([])

onMounted(async () => {
  const res = await listConsumerProjects()
  projects.value = res.items
})
</script>

<template>
  <div class="min-h-screen bg-background flex flex-col">
    <TopBar />
    <main class="flex-1 px-20 py-10">
      <div class="mb-6 flex flex-col gap-1">
        <h1 class="text-2xl font-semibold">Projecten</h1>
        <p class="text-sm text-text-secondary">Projecten die voor jouw organisatie zijn opengesteld.</p>
      </div>

      <div class="grid grid-cols-3 gap-5">
        <BaseCard v-for="p in projects" :key="p.id" hover @click="router.push({ name: 'consumer-chat', params: { id: p.id } })">
          <div class="flex flex-col items-center gap-3 py-4">
            <div class="flex h-14 w-14 items-center justify-center rounded-xl bg-consumer-light">
              <svg class="h-7 w-7 text-consumer" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/></svg>
            </div>
            <div class="text-center">
              <p class="text-sm font-semibold text-text">{{ p.name }}</p>
              <p class="mt-1 text-xs text-text-muted">Rol: {{ p.resolvedRole }} - {{ p.accessibleFileCount }} bestanden</p>
            </div>
            <BaseBadge variant="success">Toegankelijk</BaseBadge>
          </div>
        </BaseCard>
      </div>
    </main>
  </div>
</template>
