<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { getPrimaryDatasource, getTree } from '@/api/datasources'
import { getGeboraRoles, getAccessMatrix, updateAccessMatrix } from '@/api/roles'
import type { Datasource, TreeNode, GeboraRole, AccessEntry } from '@/types'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import { getErrorMessage } from '@/utils/errors'

const { nextStep, prevStep, projectId } = useStepNavigation()

const datasource = ref<Datasource | null>(null)
const tree = ref<TreeNode | null>(null)
const roles = ref<GeboraRole[]>([])
const selectedRole = ref('')
const matrix = ref<AccessEntry[]>([])
const searchQuery = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')

// Build a proper tree from flat file paths if backend returns a flat root
function buildTreeFromPaths(root: TreeNode): TreeNode {
  // Check if the root already has a proper nested structure
  const hasNestedFolders = (root.children ?? []).some(
    (c) => c.type === 'folder' && (c.children ?? []).length > 0
  )
  if (hasNestedFolders) return root

  // Backend returned flat list — rebuild tree from paths
  const files = (root.children ?? []).filter((c) => c.type === 'file')
  if (files.length === 0) return root

  const folderMap = new Map<string, TreeNode>()
  const newRoot: TreeNode = { id: 'root', path: '/', type: 'folder', name: 'root', children: [] }

  function ensureFolder(dirPath: string): TreeNode {
    if (dirPath === '' || dirPath === '/') return newRoot
    if (folderMap.has(dirPath)) return folderMap.get(dirPath)!

    const parts = dirPath.split('/')
    const name = parts.pop()!
    const parentPath = parts.join('/')
    const parent = ensureFolder(parentPath)

    const folder: TreeNode = {
      id: `folder-${dirPath}`,
      path: dirPath,
      type: 'folder',
      name,
      children: [],
    }
    folderMap.set(dirPath, folder)
    parent.children!.push(folder)
    return folder
  }

  // Also keep existing folders from backend
  for (const child of root.children ?? []) {
    if (child.type === 'folder') {
      const path = child.path.replace(/^\//, '')
      folderMap.set(path, { ...child, children: [...(child.children ?? [])] })
    }
  }

  for (const file of files) {
    const filePath = file.path.replace(/^\//, '')
    const lastSlash = filePath.lastIndexOf('/')
    if (lastSlash === -1) {
      // File at root level
      newRoot.children!.push(file)
    } else {
      const dirPath = filePath.substring(0, lastSlash)
      const folder = ensureFolder(dirPath)
      folder.children!.push(file)
    }
  }

  return newRoot
}

function countFiles(node: TreeNode): number {
  if (node.type === 'file') return 1
  return (node.children ?? []).reduce((sum, c) => sum + countFiles(c), 0)
}

const fileCount = computed(() => tree.value ? countFiles(tree.value) : 0)

const filteredRoles = computed(() =>
  roles.value.filter((r) => r.label.toLowerCase().includes(searchQuery.value.toLowerCase()))
)

const flatNodes = computed(() => {
  if (!tree.value) return []
  const nodes: Array<TreeNode & { depth: number; childCount?: number }> = []
  const walk = (node: TreeNode, depth: number) => {
    const isRoot = node.id === 'root' && node.path === '/'
    if (!isRoot) {
      const childCount = node.type === 'folder' ? (node.children ?? []).length : undefined
      nodes.push({ ...node, depth, childCount })
    }
    if (node.type === 'folder' && (isRoot || expandedFolders.value.has(node.id))) {
      for (const child of node.children ?? []) {
        walk(child, isRoot ? depth : depth + 1)
      }
    }
  }
  walk(tree.value, 0)
  return nodes
})

function hasAccess(roleCode: string, resourceId: string): boolean {
  return matrix.value.some((e) => e.roleCode === roleCode && e.resourceId === resourceId && e.allowRead)
}

function isInherited(roleCode: string, nodePath: string): boolean {
  // Check if any parent folder of this file is granted access
  const normalised = nodePath.replace(/^\//, '')
  return matrix.value.some((e) => {
    if (e.roleCode !== roleCode || !e.allowRead || e.resourceType !== 'folder') return false
    const folderPath = e.path.replace(/^\//, '')
    return normalised.startsWith(folderPath + '/') || normalised.startsWith(folderPath + '/')
  })
}

function toggleAccess(roleCode: string, resourceId: string, path: string, type: 'folder' | 'file') {
  const idx = matrix.value.findIndex((e) => e.roleCode === roleCode && e.resourceId === resourceId)
  if (idx >= 0) {
    matrix.value.splice(idx, 1)
  } else {
    matrix.value.push({ roleCode, resourceType: type, resourceId, path, allowRead: true, inherited: false })
  }
}

function accessCountForRole(roleCode: string): number {
  return matrix.value.filter((e) => e.roleCode === roleCode && e.allowRead).length
}

const expandedFolders = ref(new Set<string>())

function toggleFolder(folderId: string) {
  if (expandedFolders.value.has(folderId)) {
    expandedFolders.value.delete(folderId)
  } else {
    expandedFolders.value.add(folderId)
  }
}

// Expand all folders on first load
function expandAll(node: TreeNode) {
  if (node.type === 'folder') {
    expandedFolders.value.add(node.id)
    for (const child of node.children ?? []) expandAll(child)
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
      error.value = 'Er is nog geen databron gekoppeld aan dit project.'
      return
    }

    const treeRes = await getTree(projectId.value, datasource.value.id)
    tree.value = buildTreeFromPaths(treeRes.root)
  } catch (err) {
    error.value = getErrorMessage(err, 'Documentstructuur kon niet worden opgehaald.')
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
  <div v-if="loading" class="flex items-center gap-3 py-12 justify-center text-text-muted">
    <svg class="animate-spin h-5 w-5" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
    Documenten en rollen worden geladen...
  </div>

  <div v-else-if="error" class="border border-amber-200 bg-warning-light rounded-lg px-4 py-3 text-sm text-amber-800">
    {{ error }}
  </div>

  <div v-else-if="tree && roles.length" class="flex gap-0 -mx-20 -my-10 flex-1">
    <!-- Left sidebar: GEBORA rollen -->
    <div class="w-[280px] shrink-0 border-r border-border p-5 flex flex-col gap-4 bg-surface">
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
          class="text-left px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer flex items-center justify-between"
          :class="selectedRole === role.code ? 'bg-primary text-white font-medium' : 'text-text hover:bg-background'"
        >
          <span>{{ role.label }}</span>
          <span
            class="text-xs rounded-full px-1.5 py-0.5"
            :class="selectedRole === role.code ? 'bg-white/20 text-white' : 'bg-background text-text-muted'"
          >
            {{ accessCountForRole(role.code) }}
          </span>
        </button>
      </div>
    </div>

    <!-- Right content: bestandsboom + checkboxes -->
    <div class="flex-1 p-6 flex flex-col gap-5 overflow-auto">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-semibold">Documenten &amp; toegang</h1>
          <p class="text-sm text-text-secondary">
            Bepaal welke bestanden
            <span class="font-medium text-primary">{{ roles.find(r => r.code === selectedRole)?.label }}</span>
            mag inzien.
          </p>
        </div>
        <div class="flex items-center gap-3">
          <BaseBadge variant="primary">{{ fileCount }} documenten</BaseBadge>
        </div>
      </div>

      <div class="border border-border rounded-lg divide-y divide-border">
        <div class="grid grid-cols-[1fr_100px] items-center px-4 py-2 bg-background text-xs font-medium text-text-muted">
          <span>Bestand / map</span>
          <span class="text-center">Leestoegang</span>
        </div>
        <div
          v-for="node in flatNodes"
          :key="node.id"
          class="grid grid-cols-[1fr_100px] items-center px-4 py-2"
          :class="[
            node.type === 'folder' ? 'bg-background/50' : '',
            node.type === 'file' && isInherited(selectedRole, node.path) ? 'bg-primary-light/50' : '',
          ]"
        >
          <div
            class="flex items-center gap-1.5"
            :style="{ paddingLeft: `${node.depth * 20}px` }"
            :class="node.type === 'folder' ? 'cursor-pointer select-none' : ''"
            @click="node.type === 'folder' && toggleFolder(node.id)"
          >
            <!-- Chevron for folders -->
            <svg
              v-if="node.type === 'folder'"
              class="w-3.5 h-3.5 text-text-muted shrink-0 transition-transform"
              :class="expandedFolders.has(node.id) ? 'rotate-90' : ''"
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
            <span v-else class="w-3.5" />
            <!-- Icon -->
            <svg
              v-if="node.type === 'folder'"
              class="w-4 h-4 text-primary shrink-0"
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
            <svg
              v-else
              class="w-4 h-4 text-text-muted shrink-0"
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
            <span class="text-sm" :class="node.type === 'folder' ? 'font-medium' : ''">
              {{ displayName(node) }}
            </span>
            <span v-if="node.type === 'folder'" class="text-xs text-text-muted ml-1">
              ({{ node.childCount }})
            </span>
          </div>
          <div class="flex justify-center">
            <input
              v-if="node.type === 'folder'"
              type="checkbox"
              :checked="hasAccess(selectedRole, node.id)"
              @change="toggleAccess(selectedRole, node.id, node.path, node.type)"
              class="w-4 h-4 accent-primary cursor-pointer"
            />
            <svg
              v-else-if="isInherited(selectedRole, node.path)"
              class="w-4 h-4 text-primary/50"
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
          </div>
        </div>
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
    </div>
  </div>
</template>
