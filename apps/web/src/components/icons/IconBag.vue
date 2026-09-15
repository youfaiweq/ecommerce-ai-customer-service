<script setup lang="ts">
defineProps<{ size?: number }>()
</script>

<template>
  <svg
    :width="size ?? 18"
    :height="size ?? 18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M6 7h12l-1.2 12.4a2 2 0 0 1-2 1.6h-5.6a2 2 0 0 1-2-1.6L6 7Z" />
    <path d="M9 7V5a3 3 0 0 1 6 0v2" />
  </svg>
</template>
