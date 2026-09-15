import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import type { Product } from '@/types/product'

interface CartLine {
  product: Product
  qty: number
  variant?: string
}

const STORAGE_KEY = 'nora:cart:v1'

export const useCartStore = defineStore('cart', () => {
  const lines = ref<CartLine[]>(load())

  // Apple-style add-to-bag 反馈：
  //   lastAddedAt —— 触发袋图标脉冲 + 下拉自动展开
  //   lastAddedKey —— 高亮新加的那一行 ~1.4s
  const lastAddedAt = ref(0)
  const lastAddedKey = ref<string | null>(null)

  function load(): CartLine[] {
    if (typeof localStorage === 'undefined') return []
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return []
      const parsed = JSON.parse(raw) as CartLine[]
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }

  watch(
    lines,
    (val) => {
      if (typeof localStorage === 'undefined') return
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
      } catch {
        /* ignore */
      }
    },
    { deep: true },
  )

  function add(product: Product, qty = 1, variant?: string) {
    const key = product.id + (variant ?? '')
    const existing = lines.value.find(
      (l) => l.product.id === product.id && l.variant === variant,
    )
    if (existing) existing.qty += qty
    else lines.value.push({ product, qty, variant })
    lastAddedKey.value = key
    lastAddedAt.value = Date.now()
  }

  function remove(productId: string, variant?: string) {
    lines.value = lines.value.filter(
      (l) => !(l.product.id === productId && l.variant === variant),
    )
  }

  function setQty(productId: string, qty: number, variant?: string) {
    const line = lines.value.find(
      (l) => l.product.id === productId && l.variant === variant,
    )
    if (!line) return
    if (qty <= 0) remove(productId, variant)
    else line.qty = qty
  }

  function clear() {
    lines.value = []
  }

  const totalQty = computed(() =>
    lines.value.reduce((sum, l) => sum + l.qty, 0),
  )

  const totalPrice = computed(() =>
    lines.value.reduce((sum, l) => sum + l.qty * l.product.price, 0),
  )

  return { lines, add, remove, setQty, clear, totalQty, totalPrice, lastAddedAt, lastAddedKey }
})
