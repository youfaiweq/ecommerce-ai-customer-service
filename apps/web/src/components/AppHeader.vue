<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import IconLogo from '@/components/icons/IconLogo.vue'
import IconSearch from '@/components/icons/IconSearch.vue'
import IconUser from '@/components/icons/IconUser.vue'
import CartDropdown from '@/components/CartDropdown.vue'
import LocaleSwitcher from '@/components/LocaleSwitcher.vue'
import { useAuth } from '@/composables/useAuth'

const { t } = useI18n()
const { user, ready } = useAuth()
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-line/80 bg-white/85 backdrop-blur-xl">
    <!-- 顶部 promo bar -->
    <div class="bg-ink-primary text-2xs text-white">
      <div class="container-x flex h-7 items-center justify-center text-center font-medium tracking-wide">
        {{ t('nav.promo') }}
      </div>
    </div>

    <!-- 主导航 -->
    <div class="container-x flex h-14 items-center justify-between gap-3">
      <RouterLink to="/" class="flex items-center gap-2">
        <IconLogo :size="14" />
        <span class="text-sm font-semibold tracking-tight text-ink-primary">NORA</span>
      </RouterLink>

      <nav class="hidden items-center gap-7 md:flex">
        <RouterLink to="/" class="nav-link">{{ t('nav.shop') }}</RouterLink>
        <RouterLink to="/products?cat=headphones" class="nav-link">{{ t('nav.headphones') }}</RouterLink>
        <RouterLink to="/products?cat=watches" class="nav-link">{{ t('nav.watches') }}</RouterLink>
        <RouterLink to="/products?cat=speakers" class="nav-link">{{ t('nav.speakers') }}</RouterLink>
        <RouterLink to="/products?cat=accessories" class="nav-link">{{ t('nav.accessories') }}</RouterLink>
        <a href="#" class="nav-link">{{ t('nav.support') }}</a>
      </nav>

      <div class="flex items-center gap-2 text-ink-body sm:gap-3">
        <button class="hidden h-9 w-9 items-center justify-center rounded-pill hover:bg-bg-tint md:flex" :aria-label="t('nav.search')">
          <IconSearch />
        </button>
        <RouterLink
          v-if="ready && user"
          to="/account"
          class="hidden h-9 items-center gap-1.5 rounded-pill px-2 text-sm text-ink-body transition hover:bg-bg-tint hover:text-ink-primary md:flex"
          :aria-label="t('nav.account')"
        >
          <IconUser />
          <span class="max-w-[6rem] truncate text-2xs">{{ user.name || user.user_id }}</span>
        </RouterLink>
        <RouterLink
          v-else-if="ready"
          to="/login"
          class="hidden h-9 items-center gap-1.5 rounded-pill px-2 text-sm text-ink-body transition hover:bg-bg-tint hover:text-ink-primary md:flex"
          :aria-label="t('auth.login.title')"
        >
          <IconUser />
          <span class="text-2xs">{{ t('auth.login.title') }}</span>
        </RouterLink>
        <button
          v-else
          class="hidden h-9 w-9 items-center justify-center rounded-pill hover:bg-bg-tint md:flex"
          :aria-label="t('nav.account')"
        >
          <IconUser />
        </button>
        <LocaleSwitcher />
        <CartDropdown />
      </div>
    </div>
  </header>
</template>
