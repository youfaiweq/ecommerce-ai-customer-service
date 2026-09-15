import type { Product } from '@/types/product'

export interface ProductImageSpec {
  variant: string
  url?: string
  svg?: string
}

/**
 * 把 product.images[] 字符串 / 对象统一解析成 label + url/svg。
 * 优先使用 url（真实摄影图）；没有 url 时回退到 SVG 占位。
 * 上线时只需要在 products.json / products.ts 里给 image 对象加 url 即可。
 */
export interface RenderedImage {
  label: string
  variant: string
  url?: string
  svg?: string
}

function normalizeImage(input: string | ProductImageSpec): ProductImageSpec {
  if (typeof input === 'string') return { variant: input }
  return input
}

export function renderImages(p: Product): RenderedImage[] {
  const variants = Array.isArray(p.images)
    ? p.images.map(normalizeImage)
    : [{ variant: 'front' }]
  return variants.map((v) => ({
    label: labelOf(v.variant, p),
    variant: v.variant,
    url: v.url,
    svg: v.url ? undefined : svgFor(p, v.variant),
  }))
}

function labelOf(variant: string, p: Product): string {
  if (p.category === 'headphones' && variant === 'case') return '充电盒'
  if (variant === 'side') return '侧面'
  if (variant === 'case') return p.category === 'accessories' ? '细节' : '配件'
  return '正面'
}

function svgFor(p: Product, variant: string): string {
  const accent = p.accent_hex
  switch (p.category) {
    case 'headphones':
      return headPhoneSvg(accent, variant)
    case 'watches':
      return watchSvg(accent, variant)
    case 'speakers':
      return speakerSvg(accent, variant)
    case 'accessories':
      return accessorySvg(accent, variant)
    default:
      return `<svg viewBox="0 0 100 100" width="50%"><circle cx="50" cy="50" r="30" fill="${accent}"/></svg>`
  }
}

function headPhoneSvg(accent: string, variant: string): string {
  if (variant === 'case') {
    return `
<svg viewBox="0 0 100 100" width="50%">
  <ellipse cx="50" cy="62" rx="36" ry="22" fill="#F5F5F7" stroke="#D2D2D7" stroke-width="0.5"/>
  <circle cx="50" cy="40" r="6" fill="${accent}"/>
  <rect x="44" y="30" width="12" height="20" rx="6" fill="#0A0A0A"/>
</svg>`
  }
  if (variant === 'side') {
    return `
<svg viewBox="0 0 100 100" width="50%">
  <path d="M40,60 Q40,20 70,20" stroke="#0A0A0A" stroke-width="6" fill="none" stroke-linecap="round"/>
  <rect x="34" y="50" width="14" height="32" rx="6" fill="#0A0A0A"/>
  <ellipse cx="44" cy="80" rx="6" ry="14" fill="${accent}" opacity="0.85"/>
</svg>`
  }
  // front
  return `
<svg viewBox="0 0 100 100" width="50%">
  <path d="M20,60 Q20,18 50,18 Q80,18 80,60" stroke="#0A0A0A" stroke-width="6" fill="none" stroke-linecap="round"/>
  <rect x="14" y="50" width="18" height="36" rx="8" fill="#0A0A0A"/>
  <rect x="68" y="50" width="18" height="36" rx="8" fill="#0A0A0A"/>
  <ellipse cx="23" cy="78" rx="6" ry="14" fill="${accent}" opacity="0.85"/>
  <ellipse cx="77" cy="78" rx="6" ry="14" fill="${accent}" opacity="0.85"/>
</svg>`
}

function watchSvg(accent: string, variant: string): string {
  if (variant === 'side') {
    return `
<svg viewBox="0 0 100 100" width="50%">
  <rect x="40" y="20" width="20" height="60" rx="8" fill="#0A0A0A"/>
  <rect x="46" y="28" width="8" height="44" rx="2" fill="${accent}"/>
</svg>`
  }
  return `
<svg viewBox="0 0 100 100" width="50%">
  <rect x="32" y="28" width="36" height="44" rx="8" fill="#0A0A0A"/>
  <rect x="38" y="36" width="24" height="24" rx="3" fill="${accent}"/>
  <rect x="40" y="20" width="20" height="10" rx="2" fill="#1D1D1F"/>
  <rect x="40" y="70" width="20" height="10" rx="2" fill="#1D1D1F"/>
</svg>`
}

function speakerSvg(accent: string, _variant: string): string {
  return `
<svg viewBox="0 0 100 100" width="50%">
  <rect x="36" y="20" width="28" height="60" rx="6" fill="#1D1D1F"/>
  <circle cx="50" cy="38" r="6" fill="${accent}"/>
  <circle cx="50" cy="56" r="8" fill="#9CA0A8"/>
  <circle cx="50" cy="72" r="3" fill="#9CA0A8"/>
</svg>`
}

function accessorySvg(accent: string, variant: string): string {
  if (variant === 'side') {
    return `
<svg viewBox="0 0 100 100" width="50%">
  <rect x="20" y="46" width="60" height="6" rx="3" fill="#0A0A0A"/>
  <circle cx="32" cy="50" r="4" fill="${accent}"/>
  <circle cx="50" cy="50" r="4" fill="#0071E3"/>
</svg>`
  }
  // 通用：充电器 / 线
  return `
<svg viewBox="0 0 100 100" width="50%">
  <rect x="20" y="40" width="60" height="20" rx="6" fill="#1D1D1F"/>
  <circle cx="32" cy="50" r="4" fill="${accent}"/>
  <circle cx="50" cy="50" r="4" fill="#0071E3"/>
  <rect x="44" y="22" width="12" height="14" rx="4" fill="#6E6E73"/>
  <rect x="44" y="64" width="12" height="8" rx="2" fill="#6E6E73"/>
</svg>`
}
