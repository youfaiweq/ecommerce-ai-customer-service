import type { Product } from '@/types/product'
import rawProducts from '../../../../ecommerce-ai-customer-service/data/products.json'

/**
 * 商品分类的 UI 标签（属于展示层，不属于商品数据）。
 */
export const CATEGORIES = [
  { key: 'all', label: '全部', label_en: 'All' },
  { key: 'headphones', label: '耳机', label_en: 'Headphones' },
  { key: 'watches', label: '智能手表', label_en: 'Watches' },
  { key: 'speakers', label: '音箱', label_en: 'Speakers' },
  { key: 'accessories', label: '配件', label_en: 'Accessories' },
] as const

/**
 * 离线兜底数据 —— 后端不可用时浏览器仍能完整 render。
 *
 * 单一数据源：直接引用后端 @nora/api 的 data/products.json，
 * 不再手工维护一份 TS 副本（历史上两边需要手动同步，容易不一致）。
 * Vite 会在构建时把 JSON 内联进 bundle；dev 下经 server.fs.allow 跨包读取。
 */
export const PRODUCTS: Product[] = rawProducts as unknown as Product[]
