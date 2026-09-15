<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useProductStore } from '@/stores/products'
import { useCartStore } from '@/stores/cart'
import { renderImages } from '@/composables/useProductImage'
import { pickLocalized, locale } from '@/i18n'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const products = useProductStore()
const cart = useCartStore()

const product = computed(() => products.byId(route.params.id as string))
const renderedImages = computed(() => (product.value ? renderImages(product.value) : []))
const activeImage = ref(0)
const selectedVariant = ref<string | undefined>(product.value?.variants?.[0])
const qty = ref(1)

function setActiveImage(i: number) {
  activeImage.value = i
}

function addToCart() {
  if (!product.value) return
  cart.add(product.value, qty.value, selectedVariant.value)
  router.push('/cart')
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/products')
}

const isEN = computed(() => locale.value === 'en-US')

function localName(p: any): string {
  return pickLocalized(p, 'name', 'name_en', true)
}
function localTag(p: any): string {
  return pickLocalized(p, 'tagline', 'tagline_en', true)
}
function localDesc(p: any): string {
  return pickLocalized(p, 'description', 'description_en', true)
}
function localSpec(s: any): { label: string; value: string } {
  return {
    label: pickLocalized(s, 'label', 'label_en', true),
    value: pickLocalized(s, 'value', 'value_en', true),
  }
}
</script>

<template>
  <section v-if="product" class="container-x py-12 lg:py-20">
    <nav class="mb-8 text-2xs text-ink-quiet">
      <RouterLink to="/" class="hover:text-ink-primary">{{ t('nav.shop') }}</RouterLink>
      <span class="mx-2">/</span>
      <RouterLink to="/products" class="hover:text-ink-primary">{{ product.category }}</RouterLink>
      <span class="mx-2">/</span>
      <span class="text-ink-primary">{{ localName(product) }}</span>
    </nav>

    <div class="grid grid-cols-1 gap-12 lg:grid-cols-[560px_1fr] lg:gap-22">
      <!-- 产品图集 -->
      <div>
        <div
          class="relative aspect-square overflow-hidden rounded-2xl border border-line bg-bg-tint"
        >
          <Transition name="crossfade" mode="out-in">
            <img
              v-if="renderedImages[activeImage]?.url"
              :key="renderedImages[activeImage].variant"
              :src="renderedImages[activeImage].url"
              :alt="localName(product) + ' - ' + renderedImages[activeImage].label"
              class="h-full w-full object-cover"
              loading="eager"
            />
            <div
              v-else-if="renderedImages[activeImage]?.svg"
              :key="renderedImages[activeImage].variant"
              class="flex h-full w-full items-center justify-center"
              v-html="renderedImages[activeImage].svg"
            />
          </Transition>
        </div>
        <!-- 缩略图 -->
        <div v-if="renderedImages.length > 1" class="mt-4 flex gap-3">
          <button
            v-for="(img, i) in renderedImages"
            :key="img.variant"
            type="button"
            class="thumb flex h-20 w-20 items-center justify-center overflow-hidden rounded-xl border-2 bg-bg-tint transition-all"
            :class="
              i === activeImage
                ? 'border-accent'
                : 'border-transparent hover:border-line'
            "
            @click="setActiveImage(i)"
            :aria-label="img.label"
          >
            <img
              v-if="img.url"
              :src="img.url"
              :alt="img.label"
              class="h-full w-full object-cover"
              loading="lazy"
            />
            <div
              v-else-if="img.svg"
              class="h-full w-full"
              v-html="img.svg"
            />
          </button>
        </div>
      </div>

      <!-- 产品信息 -->
      <div class="lg:pt-6">
        <p class="font-mono text-2xs uppercase tracking-[0.06em] text-ink-quiet">
          {{ product.sku }}
        </p>
        <h1 class="mt-3 text-3xl font-semibold leading-tight tracking-tight text-ink-primary">
          {{ localName(product) }}
        </h1>
        <p class="mt-3 text-lg text-ink-body">{{ localTag(product) }}</p>

        <div class="mt-6 flex items-baseline gap-3">
          <span class="text-2xl font-medium text-ink-primary">
            ¥{{ product.price.toLocaleString('zh-CN') }}
          </span>
          <span v-if="product.msrp" class="text-sm text-ink-quiet line-through">
            ¥{{ product.msrp.toLocaleString('zh-CN') }}
          </span>
        </div>

        <p class="mt-8 text-sm leading-relaxed text-ink-body">
          {{ localDesc(product) }}
        </p>

        <!-- 规格选择 -->
        <div v-if="product.variants?.length" class="mt-8">
          <p class="eyebrow mb-3">{{ t('detail.variants') }}</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="v in product.variants"
              :key="v"
              type="button"
              class="rounded-pill border px-4 py-2 text-2xs font-medium transition-colors"
              :class="
                v === selectedVariant
                  ? 'border-ink-primary text-ink-primary'
                  : 'border-line text-ink-body hover:border-ink-primary hover:text-ink-primary'
              "
              @click="selectedVariant = v"
            >
              {{ v }}
            </button>
          </div>
        </div>

        <!-- 数量 -->
        <div class="mt-8 flex items-center gap-4">
          <p class="eyebrow">{{ t('detail.quantity') }}</p>
          <div class="flex items-center rounded-pill border border-line">
            <button
              type="button"
              class="h-9 w-9 text-ink-quiet hover:text-ink-primary disabled:opacity-50"
              :disabled="qty <= 1"
              @click="qty = Math.max(1, qty - 1)"
              :aria-label="isEN ? 'Decrease' : '减少'"
            >
              −
            </button>
            <span class="w-10 text-center text-sm font-medium">{{ qty }}</span>
            <button
              type="button"
              class="h-9 w-9 text-ink-quiet hover:text-ink-primary"
              @click="qty = qty + 1"
              :aria-label="isEN ? 'Increase' : '增加'"
            >
              +
            </button>
          </div>
        </div>

        <!-- CTA -->
        <div class="mt-10 flex flex-col gap-3 sm:flex-row">
          <button
            v-if="product.stock !== 'soldout'"
            type="button"
            class="btn-primary flex-1"
            @click="addToCart"
          >
            {{ t('detail.addToBagCta') }} ¥{{ (product.price * qty).toLocaleString('zh-CN') }} ↗
          </button>
          <button v-else type="button" disabled class="btn-primary flex-1 cursor-not-allowed opacity-60">
            {{ t('products.joinWaitlist') }}
          </button>
          <button type="button" class="btn-outline" @click="goBack">{{ t('detail.continueShopping') }}</button>
        </div>

        <!-- 规格参数 -->
        <dl class="mt-12 grid grid-cols-1 gap-4 border-t border-line pt-8 sm:grid-cols-2">
          <template v-for="spec in product.specs" :key="spec.label + spec.value">
            <div class="flex gap-3">
              <dt class="w-24 text-2xs text-ink-quiet">{{ localSpec(spec).label }}</dt>
              <dd class="flex-1 text-sm text-ink-body">{{ localSpec(spec).value }}</dd>
            </div>
          </template>
        </dl>

        <!-- 配送 / 保修 -->
        <div class="mt-10 grid grid-cols-3 gap-3 text-2xs text-ink-quiet">
          <div class="rounded-xl bg-bg-tint p-3">
            <p class="font-medium text-ink-body">{{ t('detail.benefits.shipping') }}</p>
            <p class="mt-0.5">{{ t('detail.benefits.shippingNote') }}</p>
          </div>
          <div class="rounded-xl bg-bg-tint p-3">
            <p class="font-medium text-ink-body">{{ t('detail.benefits.financing') }}</p>
            <p class="mt-0.5">{{ t('detail.benefits.financingNote') }}</p>
          </div>
          <div class="rounded-xl bg-bg-tint p-3">
            <p class="font-medium text-ink-body">{{ t('detail.benefits.warranty') }}</p>
            <p class="mt-0.5">{{ t('detail.benefits.warrantyNote') }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>

  <section v-else class="container-x py-30 text-center">
    <p class="text-sm text-ink-quiet">{{ t('detail.notFound') }}</p>
    <RouterLink to="/products" class="mt-6 inline-block btn-outline">{{ t('detail.backToStore') }}</RouterLink>
  </section>
</template>

<style scoped>
.crossfade-enter-active,
.crossfade-leave-active {
  transition: opacity 260ms ease-out;
}
.crossfade-enter-from,
.crossfade-leave-to {
  opacity: 0;
}

.thumb {
  transition:
    border-color 200ms ease-out,
    transform 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.thumb:active {
  transform: scale(0.96);
}
</style>
