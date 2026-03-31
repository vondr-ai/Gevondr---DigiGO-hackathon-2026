<script setup lang="ts">
defineProps<{ currentStep: number; totalSteps: number }>()
</script>

<template>
  <span class="text-xs font-medium text-primary bg-primary-light px-3 py-1 rounded-full">
    Stap {{ currentStep }} van {{ totalSteps }}
  </span>
</template>
