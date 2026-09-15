<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useCartStore } from '@/stores/cart'
import { renderImages } from '@/composables/useProductImage'
import type { Product } from '@/types/product'

const props = defineProps<{ product: Product }>()
const { t } = useI18n()
const cart = useCartStore()

const isSoldOut = computed(() => props.product.stock === 'soldout')
const renderedImages = computed(() => renderImages(props.product))
const mainImage = computed(() => renderedImages.value[0])

const stockLabel = computed(() => {
  switch (props.product.stock) {
    case 'in_stock':
      return t('products.inStock')
    case 'low_stock':
      return t('products.lowStock')
    case 'preorder':
      return t('products.preorder')
    default:
      return t('products.waitlist')
  }
})

function quickAdd() {
  if (isSoldOut.value) return
  cart.add(props.product, 1)
}
</script>

<template>
  <article
    class="group relative flex flex-col overflow-hidden rounded-2xl border border-line bg-white transition-colors"
    :class="isSoldOut ? 'cursor-not-allowed opacity-55' : 'cursor-pointer hover:border-ink-primary'"
  >
    <!-- 价格/促销徽章：absolute 在图片区左上 -->
    <div class="absolute left-3 top-3 z-10 flex flex-col gap-1.5">
      <span
        v-if="product.badges?.includes('sale') && product.msrp"
        class="rounded-md bg-sale px-2 py-1 text-2xs font-medium text-white"
      >
        −{{ Math.round(((product.msrp - product.price) / product.msrp) * 100) }}%
      </span>
      <span
        v-if="product.badges?.includes('new')"
        class="rounded-md bg-ink-primary px-2 py-1 text-2xs font-medium text-white"
      >
        {{ t('products.badge.new') }}
      </span>
      <span
        v-if="product.badges?.includes('preorder')"
        class="rounded-md bg-preorder px-2 py-1 text-2xs font-medium text-white"
      >
        {{ t('products.badge.preorder') }}
      </span>
      <span
        v-if="isSoldOut"
        class="rounded-md bg-ink-primary px-2 py-1 text-2xs font-medium text-white"
      >
        {{ t('products.soldOut') }}
      </span>
    </div>

    <RouterLink :to="`/products/${product.id}`" class="group/img block overflow-hidden">
      <div
        class="flex aspect-square items-center justify-center overflow-hidden bg-bg-tint transition-opacity group-hover/img:opacity-95"
      >
        <img
          v-if="mainImage.url"
          :src="mainImage.url"
          :alt="product.name"
          class="h-full w-full object-cover transition-transform duration-500 ease-out group-hover/img:scale-[1.04]"
          loading="lazy"
        />
        <div
          v-else-if="mainImage.svg"
          class="flex h-full w-full items-center justify-center"
          v-html="mainImage.svg"
        />
      </div>
    </RouterLink>

    <div class="flex flex-1 flex-col gap-1.5 p-5">
      <span class="font-mono text-2xs uppercase tracking-[0.06em] text-ink-quiet">
        {{ product.sku }}
      </span>
      <h3 class="text-base font-medium leading-snug text-ink-primary">
        {{ product.name }}
      </h3>
      <p class="text-2xs text-ink-quiet">{{ product.tagline }}</p>

      <div class="mt-3 flex items-baseline gap-2">
        <span class="price">¥{{ product.price.toLocaleString('zh-CN') }}</span>
        <span v-if="product.msrp" class="price--strike text-2xs">
          ¥{{ product.msrp.toLocaleString('zh-CN') }}
        </span>
      </div>

      <div class="mt-2 flex items-center gap-2 text-2xs text-ink-quiet">
        <span
          class="inline-block h-2 w-2 rounded-pill"
          :class="{
            'bg-stock': product.stock === 'in_stock',
            'bg-preorder': product.stock === 'preorder',
            'bg-ink-primary': product.stock === 'soldout',
            'bg-sale': product.stock === 'low_stock',
          }"
        />
        <span>{{ stockLabel }}</span>
      </div>

      <button
        v-if="!isSoldOut"
        type="button"
        class="mt-3 inline-flex h-9 items-center justify-center rounded-pill border border-line text-2xs font-medium text-ink-body transition-all hover:border-ink-primary hover:text-ink-primary"
        @click="quickAdd"
      >
        {{ t('products.addToBag') }}
      </button>
      <button
        v-else
        type="button"
        disabled
        class="mt-3 inline-flex h-9 cursor-not-allowed items-center justify-center rounded-pill border border-line text-2xs font-medium text-ink-hint"
      >
        {{ t('products.joinWaitlist') }}
      </button>
    </div>
  </article>
</template>
