export type ProductCategory = 'headphones' | 'watches' | 'speakers' | 'accessories'

export type ProductBadge = 'new' | 'sale' | 'preorder' | 'soldout'

export type ProductStock = 'in_stock' | 'low_stock' | 'preorder' | 'soldout'

export interface ProductSpec {
  label: string
  label_en?: string
  value: string
  value_en?: string
}

export interface ProductImage {
  /** 渲染关键字：front / side / case / 等 */
  variant: string
  /** 远端 URL（可选） */
  url?: string
  /** 内嵌 SVG markup（当 url 不存在时） */
  svg?: string
}

export interface Product {
  id: string
  sku: string
  name: string
  name_en?: string
  tagline: string
  tagline_en?: string
  description: string
  description_en?: string
  price: number
  msrp?: number
  currency?: string
  category: ProductCategory
  variants?: string[]
  badges?: ProductBadge[]
  stock: ProductStock
  accent_hex: string
  specs: ProductSpec[]
  images?: (string | ProductImage)[]
}
