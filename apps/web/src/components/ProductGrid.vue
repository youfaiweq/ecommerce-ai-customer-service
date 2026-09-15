<script setup lang="ts">
import type { Product } from '@/types/product'
import ProductCard from './ProductCard.vue'

defineProps<{ items: Product[]; columns?: 2 | 3 | 4 }>()
</script>

<template>
  <div
    class="grid gap-5 sm:gap-6"
    :class="{
      'grid-cols-2': (columns ?? 4) >= 2,
      'md:grid-cols-3': (columns ?? 4) >= 3,
      'md:grid-cols-4': (columns ?? 4) >= 4,
    }"
  >
    <ProductCard v-for="p in items" :key="p.id" :product="p" />
  </div>
</template>
