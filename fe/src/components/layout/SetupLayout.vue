<script setup lang="ts">
import TopBar from './TopBar.vue'
import StepIndicator from './StepIndicator.vue'
import { useStepNavigation } from '@/composables/useStepNavigation'

const { currentStep, totalSteps, prevStep, nextStep } = useStepNavigation()
</script>

<template>
  <div class="min-h-screen bg-surface flex flex-col">
    <header class="flex items-center justify-between h-12 px-6 bg-surface border-b border-border">
      <div class="flex items-center gap-3">
        <img src="/logos/vondr.png" alt="Vondr" class="h-5" />
        <img src="/logos/digigo.webp" alt="DigiGO" class="h-5 rounded" />
      </div>
      <div class="flex items-center gap-4">
        <StepIndicator :current-step="currentStep" :total-steps="totalSteps" />
        <div class="w-8 h-8 rounded-full bg-primary text-white text-sm font-semibold flex items-center justify-center">V</div>
      </div>
    </header>
    <main class="flex-1 px-20 py-10 flex flex-col gap-7">
      <router-view />
    </main>
  </div>
</template>
