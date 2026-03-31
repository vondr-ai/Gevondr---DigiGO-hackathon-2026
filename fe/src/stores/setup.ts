import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Datasource, TreeNode, AiConfig, Norm, GeboraRole, AccessEntry, Delegation, IndexingSummary } from '@/types'

export const useSetupStore = defineStore('setup', () => {
  const projectId = ref<string>('')

  // Step 1: Datasources
  const datasources = ref<Datasource[]>([])
  const selectedDatasourceType = ref<string>('sharepoint')

  // Step 2: Documents
  const tree = ref<TreeNode | null>(null)
  const discovering = ref(false)

  // Step 3: AI
  const aiConfig = ref<AiConfig | null>(null)

  // Step 4: Norms
  const normsCatalog = ref<Norm[]>([])
  const selectedNorms = ref<string[]>([])
  const indexingInstructions = ref('')

  // Step 5: Access
  const geboraRoles = ref<GeboraRole[]>([])
  const accessMatrix = ref<AccessEntry[]>([])
  const selectedRole = ref<string>('')

  // Step 6: Delegations
  const delegations = ref<Delegation[]>([])

  // Step 7: Summary
  const summary = ref<IndexingSummary | null>(null)

  function reset() {
    datasources.value = []
    selectedDatasourceType.value = 'sharepoint'
    tree.value = null
    aiConfig.value = null
    normsCatalog.value = []
    selectedNorms.value = []
    indexingInstructions.value = ''
    geboraRoles.value = []
    accessMatrix.value = []
    delegations.value = []
    summary.value = null
  }

  return {
    projectId, datasources, selectedDatasourceType, tree, discovering,
    aiConfig, normsCatalog, selectedNorms, indexingInstructions,
    geboraRoles, accessMatrix, selectedRole, delegations, summary, reset,
  }
})
