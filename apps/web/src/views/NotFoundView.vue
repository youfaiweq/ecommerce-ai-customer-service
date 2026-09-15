<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <section class="container-x flex flex-col items-center py-30 text-center">
    <p class="eyebrow">{{ t('notFound.eyebrow') }}</p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-ink-primary">
      {{ t('notFound.title') }}
    </h1>
    <p class="mt-3 max-w-sm text-sm text-ink-quiet">
      {{ t('notFound.body') }}
    </p>
    <RouterLink to="/" class="btn-primary mt-8">{{ t('notFound.back') }}</RouterLink>
  </section>
</template>
