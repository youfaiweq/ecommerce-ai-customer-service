<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { locale } from '@/i18n'

const { t } = useI18n()
const year = new Date().getFullYear()
const isEN = computed(() => locale.value === 'en-US')
</script>

<template>
  <footer class="bg-bg-tint">
    <div class="container-x py-20">
      <div class="grid grid-cols-2 gap-10 md:grid-cols-4">
        <div class="col-span-2 md:col-span-1">
          <p class="text-sm font-semibold tracking-tight text-ink-primary">NORA · 商店</p>
          <p class="mt-3 max-w-[220px] text-2xs text-ink-quiet">
            {{ t('footer.tagline') }}
          </p>
        </div>

        <div>
          <p class="eyebrow mb-4">{{ t('footer.sections.products') }}</p>
          <ul class="space-y-2 text-sm text-ink-body">
            <li><a href="#" class="hover:text-ink-primary">{{ t('nav.headphones') }}</a></li>
            <li><a href="#" class="hover:text-ink-primary">{{ t('nav.watches') }}</a></li>
            <li><a href="#" class="hover:text-ink-primary">{{ t('nav.speakers') }}</a></li>
            <li><a href="#" class="hover:text-ink-primary">{{ t('nav.accessories') }}</a></li>
          </ul>
        </div>

        <div>
          <p class="eyebrow mb-4">{{ t('footer.sections.support') }}</p>
          <ul class="space-y-2 text-sm text-ink-body">
            <li><a href="#" class="hover:text-ink-primary">{{ isEN ? 'Contact' : '联系客服' }}</a></li>
            <li><a href="#" class="hover:text-ink-primary">{{ isEN ? 'Order lookup' : '订单查询' }}</a></li>
            <li><a href="#" class="hover:text-ink-primary">{{ isEN ? 'Warranty' : '保修政策' }}</a></li>
            <li><a href="#" class="hover:text-ink-primary">{{ isEN ? 'Returns' : '退换货' }}</a></li>
          </ul>
        </div>

        <div>
          <p class="eyebrow mb-4">Newsletter</p>
          <p class="mb-3 text-2xs text-ink-quiet">{{ t('footer.subscribeLead') }}</p>
          <form class="flex gap-1">
            <input
              type="email"
              :placeholder="isEN ? 'you@example.com' : 'you@example.com'"
              class="flex-1 rounded-md border border-line bg-white px-3 py-2 text-sm placeholder:text-ink-hint focus:border-ink-primary focus:outline-none"
              :aria-label="isEN ? 'email' : '邮箱'"
            />
            <button
              type="submit"
              class="rounded-md bg-ink-primary px-4 py-2 text-2xs font-medium text-white hover:bg-ink-body"
            >
              {{ t('footer.subscribeCta') }}
            </button>
          </form>
        </div>
      </div>

      <div class="mt-16 flex flex-col items-start justify-between gap-3 border-t border-line pt-6 text-2xs text-ink-quiet md:flex-row md:items-center">
        <span>© {{ year }} NORA Inc. {{ t('footer.legal') }}</span>
        <span class="flex gap-5">
          <a href="#">{{ isEN ? 'Privacy' : '隐私' }}</a>
          <a href="#">{{ isEN ? 'Terms' : '使用条款' }}</a>
          <a href="#">{{ isEN ? 'Sales policy' : '销售政策' }}</a>
          <a href="#">沪 ICP 备 0000000 号</a>
        </span>
      </div>
    </div>
  </footer>
</template>
