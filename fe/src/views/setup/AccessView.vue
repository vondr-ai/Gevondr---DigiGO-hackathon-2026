<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { getGeboraRoles, getAccessMatrix, updateAccessMatrix } from '@/api/roles'
import { getPrimaryDatasource, getTree } from '@/api/datasources'
import type { GeboraRole, AccessEntry, Datasource, TreeNode } from '@/types'
import BaseButton from '@/components/ui/BaseButton.vue'
import { getErrorMessage } from '@/utils/errors'

const { nextStep, prevStep, projectId } = useStepNavigation()

const roles = ref<GeboraRole[]>([])
const selectedRole = ref('')
const matrix = ref<AccessEntry[]>([])
const datasource = ref<Datasource | null>(null)
const tree = ref<TreeNode | null>(null)
const searchQuery = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')

const filteredRoles = computed(() =>
  roles.value.filter((r) => r.label.toLowerCase().includes(searchQuery.value.toLowerCase()))
)

const visibleNodes = computed(() => {
  if (!tree.value) return []

  const nodes: Array<TreeNode & { depth: number }> = []

  const walk = (node: TreeNode, depth: number) => {
    if (!(node.id === 'root' && node.path === '/')) {
      nodes.push({ ...node, depth })
    }
    if (node.type === 'folder') {
      for (const child of node.children ?? []) {
        walk(child, node.id === 'root' && node.path === '/' ? depth : depth + 1)
      }
    }
  }

  walk(tree.value, 0)
  return nodes
})

function hasAccess(roleCode: string, resourceId: string): boolean {
  return matrix.value.some((e) => e.roleCode === roleCode && e.resourceId === resourceId && e.allowRead)
}

function toggleAccess(roleCode: string, resourceId: string, path: string, type: 'folder' | 'file') {
  const idx = matrix.value.findIndex((e) => e.roleCode === roleCode && e.resourceId === resourceId)
  if (idx >= 0) {
    matrix.value.splice(idx, 1)
  } else {
    matrix.value.push({ roleCode, resourceType: type, resourceId, path, allowRead: true, inherited: false })
  }
}

function displayName(node: TreeNode) {
  return node.name ?? node.path.split('/').pop() ?? node.path
}

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    const [rolesRes, matrixRes, currentDatasource] = await Promise.all([
      getGeboraRoles(),
      getAccessMatrix(projectId.value),
      getPrimaryDatasource(projectId.value),
    ])
    roles.value = rolesRes.items
    matrix.value = matrixRes.entries.filter((entry) => entry.allowRead)
    datasource.value = currentDatasource
    if (roles.value.length) selectedRole.value = roles.value[0].code

    if (!datasource.value) {
      error.value = 'Er is nog geen databron beschikbaar om rechten op te zetten.'
      return
    }

    const treeRes = await getTree(projectId.value, datasource.value.id)
    tree.value = treeRes.root
  } catch (err) {
    error.value = getErrorMessage(err, 'Rechtenmatrix kon niet worden geladen.')
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  error.value = ''
  try {
    await updateAccessMatrix(projectId.value, matrix.value)
    nextStep()
  } catch (err) {
    error.value = getErrorMessage(err, 'Opslaan van de toegangsregels is mislukt.')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="flex gap-0 -mx-20 -my-10 flex-1">
    <!-- Left sidebar -->
    <div class="w-[300px] shrink-0 border-r border-border p-5 flex flex-col gap-4 bg-surface">
      <p class="text-xs font-semibold text-text-muted uppercase tracking-wider">Ketenrollen (GEBORA)</p>
      <input
        v-model="searchQuery"
        type="text"
        placeholder="Zoek rol..."
        class="px-3 py-1.5 text-sm border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
      <div class="flex flex-col gap-1">
        <button
          v-for="role in filteredRoles"
          :key="role.code"
          @click="selectedRole = role.code"
          class="text-left px-3 py-2 rounded-lg text-sm transition-colors cursor-pointer"
          :class="selectedRole === role.code ? 'bg-primary text-white font-medium' : 'text-text hover:bg-background'"
        >
          {{ role.label }}
        </button>
      </div>
    </div>

    <!-- Right content -->
    <div class="flex-1 p-6 flex flex-col gap-5">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-semibold">Toegang per rol</h1>
          <p class="text-sm text-text-secondary">Bepaal welke bestanden en mappen elke ketenrol mag inzien.</p>
        </div>
        <BaseButton variant="secondary" size="sm" :disabled="true">
          {{ datasource?.displayName ?? 'Nog geen databron' }}
        </BaseButton>
      </div>

      <div v-if="loading" class="flex items-center gap-3 py-12 justify-center text-text-muted">
        <svg class="animate-spin h-5 w-5" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
        Rechtenmatrix wordt geladen...
      </div>

      <div v-else-if="error" class="border border-amber-200 bg-warning-light rounded-lg px-4 py-3 text-sm text-amber-800">
        {{ error }}
      </div>

      <div v-else-if="tree && selectedRole" class="border border-border rounded-lg divide-y divide-border">
        <div class="grid grid-cols-[1fr_120px] items-center px-4 py-2 bg-background text-xs font-medium text-text-muted">
          <span>Bestand/map</span>
          <span class="text-center">Leestoegang</span>
        </div>
        <div
          v-for="node in visibleNodes"
          :key="node.id"
          class="grid grid-cols-[1fr_120px] items-center px-4 py-2.5"
          :class="node.type === 'file' ? 'bg-gray-50/50' : ''"
        >
          <div class="flex items-center gap-2" :style="{ paddingLeft: `${node.depth * 20}px` }">
            <svg
              v-if="node.type === 'folder'"
              class="w-4 h-4 text-primary"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
            <svg
              v-else
              class="w-4 h-4 text-text-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
            <span class="text-sm" :class="node.type === 'folder' ? 'font-medium' : ''">
              {{ displayName(node) }}
            </span>
          </div>
          <div class="flex justify-center">
            <input
              type="checkbox"
              :checked="hasAccess(selectedRole, node.id)"
              @change="toggleAccess(selectedRole, node.id, node.path, node.type)"
              class="w-4 h-4 accent-primary"
            />
          </div>
        </div>
      </div>

      <div class="flex justify-between">
        <BaseButton variant="ghost" @click="prevStep">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 17l-5-5m0 0l5-5m-5 5h12"/></svg>
          Terug
        </BaseButton>
        <BaseButton @click="save" :loading="saving" :disabled="!tree || !selectedRole">
          Volgende
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
        </BaseButton>
      </div>
    </div>
  </div>
</template>
