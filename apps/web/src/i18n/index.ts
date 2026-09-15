import { computed, ref, watch } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN'
import enUS from './en-US'

export type Locale = 'zh-CN' | 'en-US'

const STORAGE_KEY = 'nora:locale:v1'

function detectInitial(): Locale {
  if (typeof localStorage !== 'undefined') {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh-CN' || saved === 'en-US') return saved
  }
  if (typeof navigator !== 'undefined') {
    return navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
  }
  return 'zh-CN'
}

export const locale = ref<Locale>(detectInitial())

export const i18n = createI18n({
  legacy: false,
  locale: locale.value,
  fallbackLocale: 'en-US',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

watch(locale, (val) => {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, val)
  i18n.global.locale.value = val
})

export function setLocale(val: Locale) {
  locale.value = val
}

export function pickLocalized<T extends Record<string, any>>(
  obj: T,
  key: keyof T,
  enKey: keyof T,
  fallbackZh = true,
): string {
  const cur = locale.value
  if (cur === 'en-US') {
    return (obj[enKey] as string) || (fallbackZh ? (obj[key] as string) : '') || ''
  }
  return (obj[key] as string) || (obj[enKey] as string) || ''
}

export const isEN = computed(() => locale.value === 'en-US')
