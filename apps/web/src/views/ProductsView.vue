<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ProductGrid from '@/components/ProductGrid.vue'
import { useProductStore } from '@/stores/products'
import { CATEGORIES } from '@/data/products'
import { locale } from '@/i18n'

const route = useRoute()
const { t } = useI18n()
const products = useProductStore()

type CatKey = 'all' | 'headphones' | 'watches' | 'speakers' | 'accessories'
const activeCategory = ref<CatKey>('all')

watchEffect(() => {
  const cat = (route.query.cat as string) || 'all'
  activeCategory.value = (cat as CatKey) || 'all'
})

const items = computed(() => products.byCategory(activeCategory.value))
const title = computed(() => {
  const c = CATEGORIES.find((x) => x.key === activeCategory.value)
  if (!c) return t('home.series.title')
  return locale.value === 'en-US' ? c.label_en : c.label
})
</script>

<template>
  <section class="container-x py-12 lg:py-20">
    <header class="mb-10 border-b border-line pb-6">
      <p class="eyebrow">{{ t('home.series.eyebrow') }}</p>
      <h1 class="mt-3 text-2xl font-semibold tracking-tight text-ink-primary">
        {{ title }}
      </h1>
      <p class="mt-1 text-2xs text-ink-quiet">{{ items.length }} {{ locale === 'en-US' ? 'items' : '件商品' }}</p>
    </header>

    <div class="mb-8 flex flex-wrap gap-1.5">
      <RouterLink
        v-for="c in CATEGORIES"
        :key="c.key"
        :to="`/products?cat=${c.key}`"
        class="pill-tag hover:bg-line-thin"
        :class="{
          '!bg-ink-primary !text-white hover:!bg-ink-body':
            c.key === activeCategory,
        }"
      >
        {{ locale === 'en-US' ? c.label_en : c.label }}
      </RouterLink>
    </div>

    <ProductGrid :items="items" :columns="4" />
  </section>
</template>
