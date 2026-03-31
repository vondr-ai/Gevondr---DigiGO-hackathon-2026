<script setup lang="ts">
defineProps<{ variant?: 'success' | 'warning' | 'info' | 'neutral' | 'primary' }>()
</script>

<template>
  <span
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
    :class="[
      variant === 'success' ? 'bg-consumer-light text-consumer' :
      variant === 'warning' ? 'bg-warning-light text-amber-700' :
      variant === 'primary' ? 'bg-primary-light text-primary' :
      variant === 'info' ? 'bg-blue-50 text-blue-700' :
      'bg-gray-100 text-text-secondary',
    ]"
  >
    <slot />
  </span>
</template>
