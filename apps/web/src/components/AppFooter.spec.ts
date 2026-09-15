import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import AppFooter from './AppFooter.vue'
import { i18n, setLocale } from '@/i18n'

describe('AppFooter', () => {
  beforeEach(() => setLocale('zh-CN'))
  afterEach(() => setLocale('zh-CN'))

  it('updates locale-specific support labels reactively', async () => {
    const wrapper = mount(AppFooter, { global: { plugins: [i18n] } })
    expect(wrapper.text()).toContain('联系客服')

    setLocale('en-US')
    await nextTick()
    expect(wrapper.text()).toContain('Contact')
    expect(wrapper.text()).toContain('Privacy')
  })
})
