<script setup lang="ts">
defineProps<{ modelValue: boolean; label?: string }>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <label class="flex items-center gap-2 cursor-pointer">
    <input
      type="checkbox"
      :checked="modelValue"
      @change="$emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
      class="w-4 h-4 rounded border-border text-primary accent-primary"
    />
    <span v-if="label" class="text-sm text-text">{{ label }}</span>
    <slot />
  </label>
</template>
