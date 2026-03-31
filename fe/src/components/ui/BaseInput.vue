<script setup lang="ts">
defineProps<{ label?: string; type?: string; placeholder?: string; helpText?: string; modelValue?: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <label v-if="label" class="text-sm font-medium text-text">{{ label }}</label>
    <input
      :type="type ?? 'text'"
      :placeholder="placeholder"
      :value="modelValue"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      class="px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
    />
    <p v-if="helpText" class="text-xs text-text-muted">{{ helpText }}</p>
  </div>
</template>
