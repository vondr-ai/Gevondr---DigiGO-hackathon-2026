<script setup lang="ts">
defineProps<{ open: boolean; maxWidth?: string }>()
defineEmits<{ close: [] }>()
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/40" @click="$emit('close')" />
      <div
        class="relative bg-surface rounded-xl shadow-2xl"
        :style="{ maxWidth: maxWidth ?? '520px', width: '100%' }"
      >
        <slot />
      </div>
    </div>
  </Teleport>
</template>
