<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useCartStore } from '@/stores/cart'
import { locale } from '@/i18n'

const { t } = useI18n()
const cart = useCartStore()
const { lines, totalQty, totalPrice, lastAddedAt, lastAddedKey } = storeToRefs(cart)

const open = ref(false)
const root = ref<HTMLElement | null>(null)

/* ---- Apple-style add-to-bag 反馈 ---- */
// 1) 袋图标脉冲：totalQty 增加时给按钮加 0.48s 弹性缩放 class
const isPulsing = ref(false)
const prevQty = ref(totalQty.value)
watch(totalQty, (n) => {
  if (n > prevQty.value) {
    isPulsing.value = true
    setTimeout(() => { isPulsing.value = false }, 520)
  }
  prevQty.value = n
})

// 2) 下拉自动展开：lastAddedAt 变化 → 250ms 后展开（让点击有触感）
let autoOpenTimer: number | null = null
watch(lastAddedAt, (t) => {
  if (t === 0) return
  if (autoOpenTimer) window.clearTimeout(autoOpenTimer)
  autoOpenTimer = window.setTimeout(() => { open.value = true }, 250)
})
onBeforeUnmount(() => {
  if (autoOpenTimer) window.clearTimeout(autoOpenTimer)
})

// 3) 高亮新加的那一行 ~1.4s（用 store 的 lastAddedKey 匹配）
const highlightedKey = ref<string | null>(null)
let highlightTimer: number | null = null
watch(lastAddedKey, (k) => {
  if (!k) return
  highlightedKey.value = k
  if (highlightTimer) window.clearTimeout(highlightTimer)
  highlightTimer = window.setTimeout(() => {
    highlightedKey.value = null
  }, 1400)
})
onBeforeUnmount(() => {
  if (highlightTimer) window.clearTimeout(highlightTimer)
})

function toggle() {
  open.value = !open.value
  if (open.value) {
    // Defer to allow click event to settle then attach outside listener.
    setTimeout(() => document.addEventListener('click', onDocClick, { once: true }), 0)
  }
}

function onDocClick(e: MouseEvent) {
  if (!root.value) return
  if (!root.value.contains(e.target as Node)) {
    open.value = false
  } else {
    setTimeout(() => document.addEventListener('click', onDocClick, { once: true }), 0)
  }
}

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})

const isEN = computed(() => locale.value === 'en-US')
const take = computed(() => lines.value.slice(0, 3))
const moreCount = computed(() => Math.max(0, lines.value.length - 3))

function lineKey(line: { product: { id: string }; variant?: string }) {
  return line.product.id + (line.variant ?? '')
}
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="bag-btn"
      :class="{ 'bag-btn--pulse': isPulsing }"
      aria-label="cart"
      @click.stop="toggle"
    >
      <!-- bag icon -->
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 7h12l-1.2 12.4a2 2 0 0 1-2 1.6h-5.6a2 2 0 0 1-2-1.6L6 7Z" />
        <path d="M9 7V5a3 3 0 0 1 6 0v2" />
      </svg>
      <span
        v-if="totalQty > 0"
        class="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-pill bg-accent px-1 text-2xs font-medium text-white"
      >
        {{ totalQty }}
      </span>
    </button>

    <Transition name="drop">
      <div
        v-if="open"
        class="absolute right-0 top-12 z-50 w-[360px] overflow-hidden rounded-2xl border border-line bg-white shadow-[0_24px_48px_-12px_rgba(0,0,0,0.18)]"
        role="dialog"
      >
        <header class="flex items-center justify-between border-b border-line px-5 py-4">
          <p class="text-sm font-medium text-ink-primary">
            {{ t('cart.title') }}
          </p>
          <button
            type="button"
            class="text-2xs text-ink-quiet hover:text-ink-primary"
            @click="open = false"
          >
            {{ isEN ? 'Close' : '关闭' }}
          </button>
        </header>

        <div v-if="lines.length === 0" class="px-5 py-10 text-center">
          <p class="text-2xs text-ink-quiet">{{ t('cart.empty') }}</p>
          <RouterLink
            to="/products"
            class="mt-3 inline-block text-2xs text-accent hover:underline"
            @click="open = false"
          >
            {{ t('cart.browse') }} →
          </RouterLink>
        </div>

        <ul v-else class="max-h-[320px] divide-y divide-line overflow-y-auto">
          <li
            v-for="line in take"
            :key="lineKey(line)"
            class="line-row flex gap-3 px-5 py-4"
            :class="{ 'line-row--highlight': highlightedKey === lineKey(line) }"
          >
            <div class="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-xl bg-bg-tint">
              <span class="font-mono text-2xs text-ink-quiet">
                {{ line.product.sku.split(' · ')[1] }}
              </span>
            </div>
            <div class="flex flex-1 flex-col">
              <p class="truncate text-sm font-medium text-ink-primary">
                {{ line.product.name }}
              </p>
              <p class="text-2xs text-ink-quiet">
                {{ line.variant || line.product.tagline }} · ×{{ line.qty }}
              </p>
            </div>
            <p class="price whitespace-nowrap text-2xs">
              ¥{{ (line.product.price * line.qty).toLocaleString('zh-CN') }}
            </p>
          </li>
          <li v-if="moreCount > 0" class="px-5 py-3 text-center text-2xs text-ink-quiet">
            {{ isEN ? `+${moreCount} more items` : `还有 ${moreCount} 件` }}
          </li>
        </ul>

        <footer
          v-if="lines.length > 0"
          class="space-y-3 border-t border-line bg-bg-tint px-5 py-4"
        >
          <div class="flex items-baseline justify-between">
            <span class="text-2xs text-ink-quiet">{{ t('cart.subtotal') }}</span>
            <span class="price text-sm font-medium">
              ¥{{ totalPrice.toLocaleString('zh-CN') }}
            </span>
          </div>
          <RouterLink
            to="/cart"
            class="btn-primary w-full"
            @click="open = false"
          >
            {{ isEN ? 'View bag' : '查看购物袋' }} →
          </RouterLink>
          <RouterLink
            to="/products"
            class="block text-center text-2xs text-ink-quiet hover:text-ink-primary"
            @click="open = false"
          >
            {{ t('cart.continue') }}
          </RouterLink>
        </footer>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.drop-enter-active,
.drop-leave-active {
  transition:
    transform 220ms cubic-bezier(0.32, 0.72, 0, 1),
    opacity 180ms ease-out;
  transform-origin: top right;
}
.drop-enter-from,
.drop-leave-to {
  transform: translateY(-6px) scale(0.98);
  opacity: 0;
}

/* Apple-style bag-icon 弹性脉冲：缩 1→1.18→0.96→1，~480ms */
.bag-btn {
  position: relative;
  display: flex;
  height: 2.25rem;
  width: 2.25rem;
  align-items: center;
  justify-content: center;
  border-radius: 9999px;
  color: var(--color-ink-body, #1d1d1f);
  transition: background-color 160ms ease-out;
}
.bag-btn:hover {
  background-color: var(--color-bg-tint, #f5f5f7);
}
.bag-btn--pulse {
  animation: bag-bounce 480ms cubic-bezier(0.32, 0.72, 0, 1);
}
@keyframes bag-bounce {
  0%   { transform: scale(1); }
  35%  { transform: scale(1.18); }
  70%  { transform: scale(0.96); }
  100% { transform: scale(1); }
}

/* 新加一行时 ~1.4s 淡入高亮（primary 软色） */
.line-row {
  position: relative;
  transition: background-color 280ms ease-out;
}
.line-row--highlight {
  animation: line-flash 1.4s ease-out;
}
@keyframes line-flash {
  0%   { background-color: rgba(0, 113, 227, 0.14); }
  60%  { background-color: rgba(0, 113, 227, 0.08); }
  100% { background-color: transparent; }
}
</style>
