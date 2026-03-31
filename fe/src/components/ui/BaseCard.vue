<script setup lang="ts">
defineProps<{ hover?: boolean; selected?: boolean; dashed?: boolean }>()
</script>

<template>
  <div
    class="bg-surface rounded-xl border p-5 transition-all"
    :class="[
      selected ? 'border-primary bg-primary-light shadow-md shadow-primary/10' :
      dashed ? 'border-dashed border-border' :
      'border-border shadow-sm shadow-black/[0.04]',
      hover ? 'hover:shadow-md hover:border-primary/40 cursor-pointer' : '',
    ]"
  >
    <slot />
  </div>
</template>
