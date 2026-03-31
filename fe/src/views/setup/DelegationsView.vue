<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useStepNavigation } from '@/composables/useStepNavigation'
import { getDelegations, searchParticipants, updateDelegations } from '@/api/delegations'
import { getGeboraRoles } from '@/api/roles'
import type { Delegation, GeboraRole, Participant } from '@/types'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseBadge from '@/components/ui/BaseBadge.vue'
import { getErrorMessage } from '@/utils/errors'

const { nextStep, prevStep, projectId } = useStepNavigation()
const saving = ref(false)
const error = ref('')

const roles = ref<GeboraRole[]>([])
const delegations = ref<Delegation[]>([])
const allParticipants = ref<Participant[]>([])
const expandedRole = ref<string | null>(null)
const roleFilter = ref('')
const participantFilters = ref<Record<string, string>>({})

const delegationsByRole = (code: string) => delegations.value.filter((d) => d.roleCode === code)

const filteredRoles = computed(() => {
  const q = roleFilter.value.toLowerCase()
  return roles.value.filter((r) => r.label.toLowerCase().includes(q) || r.code.toLowerCase().includes(q))
})

const sortedRoles = computed(() => {
  const assigned = filteredRoles.value.filter((r) => delegationsByRole(r.code).length > 0)
  const unassigned = filteredRoles.value.filter((r) => delegationsByRole(r.code).length === 0)
  return [...assigned, ...unassigned]
})

function filteredParticipants(roleCode: string) {
  const q = (participantFilters.value[roleCode] ?? '').toLowerCase()
  if (!q) return allParticipants.value
  return allParticipants.value.filter((p) => p.name.toLowerCase().includes(q) || p.partyId.toLowerCase().includes(q))
}

function toggleRole(code: string) {
  expandedRole.value = expandedRole.value === code ? null : code
}

function isAssigned(roleCode: string, partyId: string): boolean {
  return delegations.value.some((d) => d.roleCode === roleCode && d.partyId === partyId)
}

function toggleParticipant(roleCode: string, p: Participant) {
  if (isAssigned(roleCode, p.partyId)) {
    delegations.value = delegations.value.filter((d) => !(d.roleCode === roleCode && d.partyId === p.partyId))
  } else {
    delegations.value.push({ roleCode, partyId: p.partyId, partyName: p.name })
  }
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    await updateDelegations(
      projectId.value,
      delegations.value.map((d) => ({ roleCode: d.roleCode, partyId: d.partyId })),
    )
    nextStep()
  } catch (err) {
    error.value = getErrorMessage(err, 'Delegaties opslaan is mislukt.')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    const [rolesRes, delRes, participantsRes] = await Promise.all([
      getGeboraRoles(),
      getDelegations(projectId.value),
      searchParticipants(''),
    ])
    roles.value = rolesRes.items
    delegations.value = delRes.items
    allParticipants.value = participantsRes.items

    const firstAssigned = roles.value.find((r) => delegationsByRole(r.code).length > 0)
    expandedRole.value = firstAssigned?.code ?? roles.value[0]?.code ?? null
  } catch (err) {
    error.value = getErrorMessage(err, 'Delegaties konden niet worden geladen.')
  }
})
</script>

<template>
  <div class="flex flex-col gap-1">
    <h1 class="text-2xl font-semibold">Organisaties toewijzen aan rollen</h1>
    <p class="text-sm text-text-secondary">Wijs DSGO-deelnemers toe aan de ketenrollen op dit project. Klik op een rol om deelnemers te selecteren.</p>
  </div>

  <input
    v-model="roleFilter"
    type="text"
    placeholder="Zoek ketenrol..."
    class="px-4 py-2.5 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary w-full"
  />

  <p v-if="error" class="border border-red-200 bg-red-50 rounded-lg px-4 py-3 text-sm text-red-700">
    {{ error }}
  </p>

  <div class="flex flex-col gap-2">
    <div
      v-for="role in sortedRoles"
      :key="role.code"
      class="border border-border rounded-xl overflow-hidden transition-all"
    >
      <!-- Accordion header -->
      <button
        @click="toggleRole(role.code)"
        class="w-full flex items-center justify-between px-5 py-3.5 text-left cursor-pointer hover:bg-background/50 transition-colors"
        :class="delegationsByRole(role.code).length > 0 ? 'bg-primary-light/30' : ''"
      >
        <div class="flex items-center gap-3">
          <svg
            class="w-4 h-4 text-text-muted shrink-0 transition-transform"
            :class="expandedRole === role.code ? 'rotate-90' : ''"
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          ><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
          <span class="text-sm font-medium">{{ role.label }}</span>
          <span v-if="role.description" class="text-xs text-text-muted hidden sm:inline">— {{ role.description }}</span>
        </div>
        <div class="flex items-center gap-2">
          <BaseBadge v-if="delegationsByRole(role.code).length > 0" variant="success">
            {{ delegationsByRole(role.code).length }} toegewezen
          </BaseBadge>
          <span v-else class="text-xs text-text-muted">Niet toegewezen</span>
        </div>
      </button>

      <!-- Expanded content -->
      <div v-if="expandedRole === role.code" class="border-t border-border px-5 py-4 flex flex-col gap-3">
        <input
          :value="participantFilters[role.code] ?? ''"
          @input="participantFilters[role.code] = ($event.target as HTMLInputElement).value"
          type="text"
          placeholder="Zoek deelnemer..."
          class="px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 w-full"
        />

        <div class="flex flex-col divide-y divide-border border border-border rounded-lg max-h-64 overflow-y-auto">
          <label
            v-for="p in filteredParticipants(role.code)"
            :key="p.partyId"
            class="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-background/50 transition-colors"
            :class="isAssigned(role.code, p.partyId) ? 'bg-primary-light/40' : ''"
          >
            <input
              type="checkbox"
              :checked="isAssigned(role.code, p.partyId)"
              @change="toggleParticipant(role.code, p)"
              class="w-4 h-4 accent-primary shrink-0"
            />
            <span class="text-sm flex-1">{{ p.name }}</span>
            <span class="flex items-center gap-1 text-xs text-text-muted">
              <span class="w-1.5 h-1.5 rounded-full bg-consumer" />
              {{ p.membershipStatus }}
            </span>
          </label>
        </div>

        <p v-if="filteredParticipants(role.code).length === 0" class="text-xs text-text-muted py-2">
          Geen deelnemers gevonden.
        </p>
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
</template>
