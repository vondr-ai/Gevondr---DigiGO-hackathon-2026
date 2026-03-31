<script setup lang="ts">
import TopBar from './TopBar.vue'
</script>

<template>
  <div class="min-h-screen bg-background flex flex-col">
    <TopBar />
    <main class="flex-1 px-20 py-10">
      <slot />
    </main>
  </div>
</template>
