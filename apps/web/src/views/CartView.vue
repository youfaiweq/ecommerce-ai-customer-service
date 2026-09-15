<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useCartStore } from '@/stores/cart'

const { t } = useI18n()
const cart = useCartStore()
const lines = computed(() => cart.lines)

function fmt(n: number) {
  return n.toLocaleString('zh-CN')
}

function checkout() {
  alert(t('cart.checkoutStub'))
}
</script>

<template>
  <section class="container-x py-12 lg:py-20">
    <header class="mb-10 border-b border-line pb-6">
      <p class="eyebrow">{{ t('cart.title') }}</p>
      <h1 class="mt-3 text-2xl font-semibold tracking-tight text-ink-primary">
        {{ t('cart.title') }}
      </h1>
      <p class="mt-1 text-2xs text-ink-quiet">
        {{ lines.length === 0 ? t('cart.empty') : t('cart.subtitle', cart.totalQty) }}
      </p>
    </header>

    <div v-if="lines.length === 0" class="py-22 text-center">
      <p class="text-base text-ink-quiet">{{ t('cart.empty') }}</p>
      <RouterLink to="/products" class="mt-6 inline-block btn-primary">{{ t('cart.browse') }}</RouterLink>
    </div>

    <div v-else class="grid grid-cols-1 gap-10 lg:grid-cols-[1fr_360px] lg:gap-22">
      <!-- 商品列表 -->
      <ul class="divide-y divide-line border-y border-line">
        <li v-for="line in lines" :key="line.product.id + (line.variant ?? '')" class="flex gap-5 py-6">
          <div class="flex h-24 w-24 flex-shrink-0 items-center justify-center rounded-xl bg-bg-tint">
            <span class="font-mono text-2xs text-ink-quiet">{{ line.product.sku.split(' · ')[1] }}</span>
          </div>
          <div class="flex flex-1 flex-col">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-base font-medium text-ink-primary">{{ line.product.name }}</p>
                <p class="mt-1 text-2xs text-ink-quiet">
                  {{ line.variant || line.product.tagline }}
                </p>
              </div>
              <p class="price whitespace-nowrap">
                ¥{{ fmt(line.product.price * line.qty) }}
              </p>
            </div>
            <div class="mt-auto flex items-center justify-between">
              <div class="flex items-center rounded-pill border border-line text-2xs">
                <button
                  type="button"
                  class="h-7 w-7 text-ink-quiet hover:text-ink-primary"
                  @click="cart.setQty(line.product.id, line.qty - 1, line.variant)"
                  aria-label="−"
                >
                  −
                </button>
                <span class="w-7 text-center font-medium text-ink-body">{{ line.qty }}</span>
                <button
                  type="button"
                  class="h-7 w-7 text-ink-quiet hover:text-ink-primary"
                  @click="cart.setQty(line.product.id, line.qty + 1, line.variant)"
                  aria-label="+"
                >
                  +
                </button>
              </div>
              <button
                type="button"
                class="text-2xs text-ink-quiet underline-offset-2 hover:text-sale hover:underline"
                @click="cart.remove(line.product.id, line.variant)"
              >
                {{ t('cart.remove') }}
              </button>
            </div>
          </div>
        </li>
      </ul>

      <!-- 汇总 -->
      <aside class="rounded-2xl bg-bg-tint p-7">
        <p class="eyebrow mb-5">{{ t('cart.summary') }}</p>
        <dl class="space-y-3 text-sm">
          <div class="flex justify-between">
            <dt class="text-ink-quiet">{{ t('cart.subtotal') }}</dt>
            <dd>¥{{ fmt(cart.totalPrice) }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-ink-quiet">{{ t('cart.shipping') }}</dt>
            <dd class="text-ink-quiet">{{ t('cart.shippingFree') }}</dd>
          </div>
          <div class="flex justify-between border-t border-line pt-3 text-base font-medium text-ink-primary">
            <dt>{{ t('cart.total') }}</dt>
            <dd>¥{{ fmt(cart.totalPrice) }}</dd>
          </div>
        </dl>

        <button type="button" class="btn-primary mt-6 w-full" @click="checkout">
          {{ t('cart.checkout') }} ¥{{ fmt(cart.totalPrice) }} ↗
        </button>

        <p class="mt-4 text-2xs text-ink-quiet">
          {{ t('cart.paymentMethods') }}
        </p>
        <RouterLink
          to="/products"
          class="mt-4 block text-center text-2xs text-ink-quiet hover:text-ink-primary"
        >
          ← {{ t('cart.continue') }}
        </RouterLink>
      </aside>
    </div>
  </section>
</template>
