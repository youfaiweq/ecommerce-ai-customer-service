<script setup lang="ts">
import { locale } from '@/i18n'
import type { Locale } from '@/i18n'

const options: Array<{ value: Locale; label: string; short: string }> = [
  { value: 'zh-CN', label: '简体中文', short: '中' },
  { value: 'en-US', label: 'English', short: 'EN' },
]

function pick(v: Locale) {
  locale.value = v
}
</script>

<template>
  <div class="flex items-center gap-0.5 rounded-pill border border-line p-0.5 text-2xs">
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      class="h-6 rounded-pill px-2.5 transition-colors"
      :class="
        locale === o.value
          ? 'bg-ink-primary text-white'
          : 'text-ink-quiet hover:text-ink-primary'
      "
      :aria-pressed="locale === o.value"
      @click="pick(o.value)"
    >
      {{ o.short }}
    </button>
  </div>
</template>
