import { defineStore } from 'pinia'
import { ref } from 'vue'
import { PRODUCTS as MOCK_PRODUCTS } from '@/data/products'
import { apiGet } from '@/lib/api'
import type { Product } from '@/types/product'

interface ProductsResponse {
  items: Product[]
  total: number
  categories: Array<{ key: string; count: number }>
}

/**
 * 商品 store —— 启动时 fetch `/api/products`，
 * 失败 graceful fallback 到本地 mock data（前端开发 / 后端未启动时仍可用）。
 */
export const useProductStore = defineStore('products', () => {
  const items = ref<Product[]>(MOCK_PRODUCTS)
  const isLive = ref(false)
  const error = ref<string | null>(null)
  const loading = ref(false)

  async function load(params?: { category?: string; q?: string }) {
    loading.value = true
    error.value = null
    try {
      const qs = new URLSearchParams()
      if (params?.category) qs.set('category', params.category)
      if (params?.q) qs.set('q', params.q)
      const url = qs.toString() ? `/api/products?${qs}` : '/api/products'
      const data = await apiGet<ProductsResponse>(url)
      items.value = data.items
      isLive.value = true
    } catch (e) {
      isLive.value = false
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  function byId(id: string): Product | undefined {
    return items.value.find((p) => p.id === id)
  }

  function byCategory(cat?: string): Product[] {
    if (!cat || cat === 'all') return items.value
    return items.value.filter((p) => p.category === cat)
  }

  function featured(): Product[] {
    return items.value.slice(0, 4)
  }

  return { items, isLive, error, loading, load, byId, byCategory, featured }
})
