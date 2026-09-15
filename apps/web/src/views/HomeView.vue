<script setup lang="ts">
import HeroSection from '@/components/HeroSection.vue'
import ProductGrid from '@/components/ProductGrid.vue'
import { useI18n } from 'vue-i18n'
import { useProductStore } from '@/stores/products'

const { t } = useI18n()
const products = useProductStore()
const featured = products.featured()
</script>

<template>
  <HeroSection />

  <!-- 系列产品 grid -->
  <section class="container-x py-12 lg:py-22">
    <ProductGrid :items="featured" :columns="4" />
  </section>

  <!-- 价值主张 -->
  <section class="container-x py-16 lg:py-20">
    <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
      <article class="rounded-2xl border border-line p-6">
        <p class="text-lg font-medium text-ink-primary">{{ t('detail.benefits.shipping') }}</p>
        <p class="mt-2 text-sm text-ink-quiet">
          {{ t('detail.benefits.shippingNote') }}
        </p>
      </article>
      <article class="rounded-2xl border border-line p-6">
        <p class="text-lg font-medium text-ink-primary">{{ t('detail.benefits.financing') }}</p>
        <p class="mt-2 text-sm text-ink-quiet">
          {{ t('detail.benefits.financingNote') }}
        </p>
      </article>
      <article class="rounded-2xl border border-line p-6">
        <p class="text-lg font-medium text-ink-primary">{{ t('detail.benefits.warranty') }}</p>
        <p class="mt-2 text-sm text-ink-quiet">
          {{ t('detail.benefits.warrantyNote') }}
        </p>
      </article>
    </div>
  </section>

  <!-- 推广：黑底 promo -->
  <section class="container-x pb-22">
    <article class="flex flex-col items-start gap-3 rounded-2xl bg-ink-primary p-10 text-white md:p-12">
      <p class="eyebrow text-ink-hint">{{ t('home.promoBlock.eyebrow') }}</p>
      <p class="text-2xl font-semibold tracking-tight md:text-2xl">
        {{ t('home.promoBlock.title') }}
      </p>
      <p class="text-sm text-ink-hint">
        {{ t('home.promoBlock.body') }}
      </p>
      <RouterLink
        to="/products?cat=headphones"
        class="mt-4 inline-flex items-center gap-1.5 rounded-pill bg-white px-6 py-3 text-sm font-medium text-ink-primary hover:bg-bg-tint"
      >
        {{ t('home.promoBlock.cta') }} <span>↗</span>
      </RouterLink>
    </article>
  </section>
</template>
