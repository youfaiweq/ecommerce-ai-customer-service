<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/composables/useAuth'

const { t } = useI18n()
const router = useRouter()
const { user, logout } = useAuth()

async function handleLogout() {
  await logout()
  await router.push('/login')
}

function formatDate(s: string | null | undefined): string {
  if (!s) return '-'
  return s.replace('T', ' ').split('.')[0]
}
</script>

<template>
  <section class="container-x py-16 md:py-24">
    <p class="eyebrow">{{ t('auth.account.eyebrow') }}</p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-ink-primary">
      {{ t('auth.account.title') }}
    </h1>
    <p class="mt-2 text-sm text-ink-quiet">{{ t('auth.account.subtitle') }}</p>

    <div class="mt-8 max-w-md rounded-2xl border border-line bg-bg-quiet p-6">
      <dl class="space-y-4">
        <div class="flex items-center justify-between gap-4 border-b border-line pb-3">
          <dt class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
            {{ t('auth.account.userId') }}
          </dt>
          <dd class="font-mono text-sm text-ink-primary">{{ user?.user_id ?? '-' }}</dd>
        </div>
        <div class="flex items-center justify-between gap-4 border-b border-line pb-3">
          <dt class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
            {{ t('auth.account.name') }}
          </dt>
          <dd class="text-sm text-ink-primary">{{ user?.name ?? '-' }}</dd>
        </div>
        <div class="flex items-center justify-between gap-4 border-b border-line pb-3">
          <dt class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
            {{ t('auth.account.email') }}
          </dt>
          <dd class="text-sm text-ink-primary">{{ user?.email ?? '-' }}</dd>
        </div>
        <div class="flex items-center justify-between gap-4">
          <dt class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
            {{ t('auth.account.createdAt') }}
          </dt>
          <dd class="text-sm text-ink-primary">{{ formatDate(user?.created_at) }}</dd>
        </div>
      </dl>

      <button
        type="button"
        class="btn-outline mt-6 w-full"
        @click="handleLogout"
      >
        {{ t('auth.account.logout') }}
      </button>
    </div>
  </section>
</template>
