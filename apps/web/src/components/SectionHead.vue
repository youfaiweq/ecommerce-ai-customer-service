<script setup lang="ts">
import { CATEGORIES } from '@/data/products'

const cats = CATEGORIES
</script>

<template>
  <section class="container-x py-20">
    <div class="mb-10 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="eyebrow">Store · 商店</p>
        <h2 class="mt-3 text-xl font-semibold tracking-tight text-ink-primary">
          全部产品
        </h2>
      </div>
      <nav class="flex flex-wrap items-center gap-1.5">
        <a
          v-for="c in cats"
          :key="c.key"
          :href="`/products?cat=${c.key}`"
          class="pill-tag hover:bg-line-thin"
          :class="{ 'bg-ink-primary text-white hover:bg-ink-body': c.key === 'all' }"
        >
          {{ c.label }}
        </a>
      </nav>
    </div>
    <slot />
  </section>
</template>
