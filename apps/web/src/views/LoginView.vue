<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { AuthError, useAuth } from '@/composables/useAuth'
import type { RegisterPayload } from '@/types/auth'

const { t } = useI18n()
const router = useRouter()
const { login, register } = useAuth()

const mode = ref<'login' | 'register'>('login')
const form = ref<RegisterPayload>({ user_id: '', password: '', name: '', email: '' })
const submitting = ref(false)
const errorMsg = ref('')
const isRegister = computed(() => mode.value === 'register')

const demoAccounts = [
  { user_id: 'u1001', name: '张伟' },
  { user_id: 'u1002', name: '王芳' },
  { user_id: 'u1003', name: '李娜' },
  { user_id: 'u1004', name: '陈晨' },
]
const demoPassword = 'demo123456'

function fillDemo(userId: string) {
  form.value.user_id = userId
  form.value.password = demoPassword
  errorMsg.value = ''
}

async function handleSubmit() {
  if (submitting.value) return
  if (!form.value.user_id.trim() || !form.value.password) {
    errorMsg.value = t('auth.errors.required')
    return
  }
  if (isRegister.value && !form.value.name.trim()) {
    errorMsg.value = t('auth.errors.required')
    return
  }
  submitting.value = true
  errorMsg.value = ''
  try {
    const payload = { ...form.value, user_id: form.value.user_id.trim(), name: form.value.name.trim(), email: form.value.email?.trim() }
    if (isRegister.value) {
      await register(payload)
    } else {
      await login({ user_id: payload.user_id, password: payload.password })
    }
    const redirect = (router.currentRoute.value.query.redirect as string) || '/account'
    await router.push(redirect)
  } catch (err) {
    if (err instanceof AuthError) {
      errorMsg.value =
        err.code === 'invalid_credentials' ? t('auth.errors.invalid') : err.message
    } else {
      errorMsg.value = (err as Error).message
    }
  } finally {
    submitting.value = false
  }
}

function switchMode(next: 'login' | 'register') {
  mode.value = next
  errorMsg.value = ''
}
</script>

<template>
  <section class="container-x flex flex-col items-center py-16 md:py-24">
    <p class="eyebrow">{{ isRegister ? t('auth.register.eyebrow') : t('auth.login.eyebrow') }}</p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-ink-primary">
      {{ isRegister ? t('auth.register.title') : t('auth.login.title') }}
    </h1>
    <p class="mt-2 max-w-sm text-center text-sm text-ink-quiet">
      {{ isRegister ? t('auth.register.subtitle') : t('auth.login.subtitle') }}
    </p>

    <form
      class="mt-8 w-full max-w-sm space-y-4"
      @submit.prevent="handleSubmit"
    >
      <label class="block">
        <span class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
          {{ t('auth.login.userIdLabel') }}
        </span>
        <input
          v-model="form.user_id"
          type="text"
          autocomplete="username"
          class="mt-1 w-full rounded-xl border border-line bg-bg px-3.5 py-2.5 text-base text-ink-body outline-none transition focus:border-ink-hint"
          :placeholder="t('auth.login.userIdPlaceholder')"
        />
      </label>

      <label v-if="isRegister" class="block">
        <span class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">{{ t('auth.register.nameLabel') }}</span>
        <input v-model="form.name" type="text" autocomplete="name" class="mt-1 w-full rounded-xl border border-line bg-bg px-3.5 py-2.5 text-base text-ink-body outline-none transition focus:border-ink-hint" :placeholder="t('auth.register.namePlaceholder')" />
      </label>

      <label class="block">
        <span class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
          {{ t('auth.login.passwordLabel') }}
        </span>
        <input
          v-model="form.password"
          type="password"
          :autocomplete="isRegister ? 'new-password' : 'current-password'"
          class="mt-1 w-full rounded-xl border border-line bg-bg px-3.5 py-2.5 text-base text-ink-body outline-none transition focus:border-ink-hint"
          :placeholder="t('auth.login.passwordPlaceholder')"
        />
      </label>

      <p
        v-if="errorMsg"
        class="rounded-lg border border-sale/30 bg-[#FFF5F4] px-3 py-2 text-2xs text-sale"
      >
        {{ errorMsg }}
      </p>

      <button
        type="submit"
        class="btn-primary w-full"
        :disabled="submitting"
      >
        {{ submitting ? t('auth.login.submitting') : (isRegister ? t('auth.register.submit') : t('auth.login.submit')) }}
      </button>

      <button type="button" class="w-full text-2xs text-accent hover:underline" @click="switchMode(isRegister ? 'login' : 'register')">
        {{ isRegister ? t('auth.register.toLogin') : t('auth.register.toRegister') }}
      </button>
    </form>

    <!-- 演示账号 -->
    <div v-if="!isRegister" class="mt-8 w-full max-w-sm rounded-2xl border border-line bg-bg-quiet p-4">
      <p class="text-2xs font-medium uppercase tracking-wide text-ink-quiet">
        {{ t('auth.demo.title') }}
      </p>
      <p class="mt-1 text-2xs text-ink-hint">
        {{ t('auth.demo.password') }}：<code class="font-mono text-ink-body">demo123456</code>
      </p>
      <div class="mt-3 grid grid-cols-2 gap-2">
        <button
          v-for="acc in demoAccounts"
          :key="acc.user_id"
          type="button"
          class="rounded-pill border border-line bg-bg px-3 py-1.5 text-2xs text-ink-body transition hover:border-accent hover:text-accent"
          @click="fillDemo(acc.user_id)"
        >
          {{ acc.user_id }} · {{ acc.name }}
        </button>
      </div>
    </div>
  </section>
</template>
