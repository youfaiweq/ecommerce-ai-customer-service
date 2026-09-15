<script setup lang="ts">
defineProps<{ size?: number }>()
</script>

<template>
  <svg
    :width="size ?? 14"
    :height="size ?? 14"
    viewBox="0 0 16 16"
    aria-hidden="true"
  >
    <path
      d="M8 1.2 14.8 8 8 14.8 1.2 8 8 1.2Z"
      fill="currentColor"
    />
    <circle cx="8" cy="8" r="2.5" fill="#0071E3" />
  </svg>
</template>
