<script setup lang="ts">
defineProps<{ modelValue: string; value: string; label: string; description?: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <label
    class="flex items-start gap-3 p-4 rounded-lg border cursor-pointer transition-all"
    :class="modelValue === value ? 'border-primary bg-primary-light' : 'border-border hover:border-primary/40'"
  >
    <input
      type="radio"
      :checked="modelValue === value"
      @change="$emit('update:modelValue', value)"
      class="mt-0.5 accent-primary"
    />
    <div>
      <div class="text-sm font-medium text-text">{{ label }}</div>
      <div v-if="description" class="text-xs text-text-muted mt-0.5">{{ description }}</div>
      <slot />
    </div>
  </label>
</template>
