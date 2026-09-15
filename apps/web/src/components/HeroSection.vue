<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { locale } from '@/i18n'
import { useProductStore } from '@/stores/products'
import { pickLocalized } from '@/i18n'

const { t } = useI18n()
const products = useProductStore()
const featured = computed(() => products.featured())
const hero = computed(() => featured.value[0])
const lang = locale

const localSpecs = computed(() => {
  const p = hero.value
  if (!p) return []
  return p.specs.slice(0, 4).map((s) => ({
    label: pickLocalized(s as any, 'label', 'label_en', true),
    value: pickLocalized(s as any, 'value', 'value_en', true),
  }))
})
</script>

<template>
  <section class="bg-white">
    <div class="container-x pt-24 pb-0 lg:pt-30">
      <p class="eyebrow">{{ t('home.eyebrow') }}</p>
      <h1 class="mt-6 max-w-3xl text-3xl font-semibold leading-[1.04] tracking-tight text-ink-primary md:text-3xl lg:text-3xl">
        {{ t('home.title') }}
      </h1>
      <p class="mt-6 max-w-xl text-lg text-ink-body" v-html="t('home.body')" />
      <div class="mt-8 flex flex-wrap items-center gap-3">
        <RouterLink to="/products/nora-pro-2" class="btn-primary">
          {{ t('home.cta') }}
          <span class="text-base leading-none opacity-80">↗</span>
        </RouterLink>
        <RouterLink to="/products/nora-pro-2" class="btn-outline">{{ t('home.secondary') }}</RouterLink>
        <span class="ml-1 text-2xs text-ink-quiet">
          {{ t('home.secondaryNote') }}
        </span>
      </div>
    </div>

    <!-- 产品大图占位 -->
    <div class="container-x pb-0 pt-12">
      <div class="relative overflow-hidden rounded-2xl border border-line bg-bg-tint">
        <svg viewBox="0 0 680 360" class="block h-auto w-full" aria-label="NORA Pro 2 product">
          <defs>
            <radialGradient id="hbg" cx="50%" cy="55%" r="60%">
              <stop offset="0%" stop-color="#FFFFFF" />
              <stop offset="100%" stop-color="#EFEFF1" />
            </radialGradient>
          </defs>
          <rect width="680" height="360" fill="url(#hbg)" />
          <ellipse cx="340" cy="240" rx="200" ry="36" fill="#000" opacity="0.06" />
          <path
            d="M210,210 Q210,90 340,90 Q470,90 470,210"
            stroke="#0A0A0A"
            stroke-width="14"
            fill="none"
            stroke-linecap="round"
          />
          <rect x="184" y="180" width="56" height="100" rx="22" fill="#0A0A0A" />
          <rect x="440" y="180" width="56" height="100" rx="22" fill="#0A0A0A" />
          <ellipse cx="212" cy="250" rx="20" ry="38" fill="#0071E3" opacity="0.85" />
          <ellipse cx="468" cy="250" rx="20" ry="38" fill="#0071E3" opacity="0.85" />
        </svg>
        <div class="absolute bottom-4 left-1/2 -translate-x-1/2 text-2xs uppercase tracking-[0.18em] text-ink-hint">
          NORA · PRO · 2
        </div>
      </div>

      <!-- Specs strip -->
      <dl class="my-12 grid grid-cols-2 gap-4 border-y border-line py-8 md:grid-cols-4">
        <div v-for="spec in localSpecs" :key="spec.label">
          <dt class="eyebrow">{{ spec.label }}</dt>
          <dd class="mt-1.5 text-lg font-medium text-ink-primary">{{ spec.value }}</dd>
        </div>
      </dl>
    </div>
  </section>
</template>
