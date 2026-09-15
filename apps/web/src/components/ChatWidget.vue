<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useChat } from '@/composables/useChat'
import { useAsr } from '@/composables/useAsr'
import { useAuth } from '@/composables/useAuth'
import { renderMarkdown } from '@/lib/markdown'
import type { ChatMessage, ChatMeta } from '@/types/chat'

const { t, tm, rt } = useI18n()
const chat = useChat()
const asr = useAsr()
const { user, ready } = useAuth()

const open = ref(false)
const draft = ref('')
const inputEl = ref<HTMLTextAreaElement | null>(null)
const scrollEl = ref<HTMLDivElement | null>(null)
const toast = ref('')
let toastTimer: number | undefined

const suggestions = computed<string[]>(() => {
  const items = tm('chat.suggestions')
  return Array.isArray(items) ? items.map((item) => rt(item)) : []
})
const showSuggestions = computed(() => chat.messages.value.length <= 1)

const statusText = computed(() => {
  if (asr.stopping.value) return t('chat.transcribing')
  if (asr.recording.value) return t('chat.recording')
  if (chat.connection.value === 'online') return t('chat.online')
  if (chat.connection.value === 'offline') return t('chat.offline')
  return t('chat.connecting')
})

function metaTags(meta?: ChatMeta): { text: string; warn?: boolean }[] {
  if (!meta) return []
  const tags: { text: string; warn?: boolean }[] = []
  if (meta.provider) {
    tags.push({
      text: `${t('chat.metaProvider')} · ${meta.provider === 'ollama' ? t('chat.providerOllama') : t('chat.providerDeepSeek')}`,
    })
  }
  if (meta.intent?.label) tags.push({ text: `${t('chat.metaIntent')} · ${meta.intent.label}` })
  if (meta.order_no) {
    tags.push({
      text: meta.order_found
        ? `${t('chat.metaOrder')} · ${meta.order_no}`
        : `${t('chat.metaOrder')} · ${meta.order_no}（${t('chat.metaOrderMissing')}）`,
      warn: !meta.order_found,
    })
  }
  if (meta.grounded && meta.sources?.length) {
    tags.push({ text: `${t('chat.metaSources')} · ${meta.sources.map((s) => s.id).join('、')}` })
  }
  if (meta.transferred) tags.push({ text: t('chat.metaTransferred'), warn: true })
  return tags
}

function showToast(msg: string) {
  toast.value = msg
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toast.value = ''), 2600)
}

function scrollToBottom() {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

watch(
  () => {
    const list = chat.messages.value
    return [list.length, list.length ? list[list.length - 1].text : '']
  },
  scrollToBottom,
)

async function handleSend() {
  const text = draft.value.trim()
  if (!text || chat.sending.value) return
  draft.value = ''
  syncHeight()
  await chat.send(text)
}

function pickSuggestion(s: string) {
  void chat.send(s)
}

async function handleClear() {
  await chat.clear(t('chat.greeting'))
}

async function handleRate(msg: ChatMessage, score: 1 | -1) {
  try {
    await chat.rate(msg, score)
  } catch {
    showToast(t('chat.feedbackFailed'))
  }
}

// ---- 语音 ----
async function toggleMic() {
  if (!asr.supported) {
    showToast(t('chat.micUnsupported'))
    return
  }
  if (asr.recording.value || asr.stopping.value) {
    asr.stop()
    return
  }
  try {
    await asr.start({
      sessionId: chat.sessionId.value,
      onPartial: (text) => {
        draft.value = text
        syncHeight()
      },
      onFinal: (text) => {
        draft.value = text
        syncHeight()
        inputEl.value?.focus()
        if (!text) showToast(t('chat.asrEmpty'))
      },
      onError: (msg) => showToast(msg),
    })
  } catch (e) {
    showToast((e as Error).message)
  }
}

function onInput() {
  syncHeight()
}

function syncHeight() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

function togglePanel() {
  open.value = !open.value
  if (open.value) {
    void chat.refreshHealth()
    scrollToBottom()
    window.setTimeout(() => inputEl.value?.focus(), 60)
  }
}

onMounted(() => {
  void chat.restore(t('chat.greeting'))
})
</script>

<template>
  <div class="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-3">
    <!-- 面板 -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 translate-y-3 scale-95"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="opacity-0 translate-y-3 scale-95"
    >
      <div
        v-if="open"
        class="flex h-[560px] max-h-[80vh] w-[min(380px,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-2xl border border-line bg-bg shadow-[0_18px_50px_rgba(0,0,0,0.18)]"
        role="dialog"
        aria-label="customer support"
      >
        <!-- 头部 -->
        <header class="flex items-center gap-3 border-b border-line bg-bg px-4 py-3">
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-primary text-[13px] font-semibold text-white"
          >
            AI
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-ink-primary">{{ t('chat.title') }}</p>
            <p class="flex items-center gap-1.5 text-2xs text-ink-quiet">
              <span
                class="inline-block h-1.5 w-1.5 rounded-full"
                :class="{
                  'bg-stock': chat.connection.value === 'online' && !asr.recording.value && !asr.stopping.value,
                  'bg-preorder': asr.recording.value,
                  'bg-ink-hint': asr.stopping.value || chat.connection.value === 'connecting',
                  'bg-sale': chat.connection.value === 'offline',
                }"
              />
              {{ statusText }}
            </p>
          </div>
          <!-- 模型切换：只传服务商名称，密钥始终留在后端。 -->
          <div class="flex shrink-0 rounded-pill bg-bg-tint p-0.5" :title="t('chat.providerLabel')">
            <button
              type="button"
              class="rounded-pill px-1.5 py-1 text-[10px] transition"
              :class="chat.provider.value === 'deepseek' ? 'bg-bg text-ink-primary shadow-sm' : 'text-ink-quiet hover:text-ink-primary'"
              :aria-pressed="chat.provider.value === 'deepseek'"
              @click="chat.setProvider('deepseek')"
            >{{ t('chat.providerDeepSeek') }}</button>
            <button
              type="button"
              class="rounded-pill px-1.5 py-1 text-[10px] transition"
              :class="chat.provider.value === 'ollama' ? 'bg-bg text-ink-primary shadow-sm' : 'text-ink-quiet hover:text-ink-primary'"
              :aria-pressed="chat.provider.value === 'ollama'"
              @click="chat.setProvider('ollama')"
            >{{ t('chat.providerOllama') }}</button>
          </div>
          <!-- 登录态标识 -->
          <RouterLink
            v-if="ready && user"
            to="/account"
            class="shrink-0 rounded-pill bg-bg-tint px-2 py-1 text-2xs text-ink-body transition hover:bg-accent-soft hover:text-accent"
            :title="t('auth.account.title')"
          >
            {{ user.name || user.user_id }}
          </RouterLink>
          <RouterLink
            v-else-if="ready"
            to="/login"
            class="shrink-0 rounded-pill border border-line px-2 py-1 text-2xs text-ink-quiet transition hover:border-accent hover:text-accent"
            :title="t('auth.login.title')"
          >
            {{ t('auth.login.title') }}
          </RouterLink>
          <button
            type="button"
            class="rounded-full p-1.5 text-ink-quiet transition hover:bg-bg-tint hover:text-ink-primary"
            :title="t('chat.clear')"
            :aria-label="t('chat.clear')"
            @click="handleClear"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
          </button>
          <button
            type="button"
            class="rounded-full p-1.5 text-ink-quiet transition hover:bg-bg-tint hover:text-ink-primary"
            :title="t('chat.close')"
            :aria-label="t('chat.close')"
            @click="open = false"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </header>

        <!-- 消息区 -->
        <div ref="scrollEl" class="cs-scroll flex-1 space-y-4 overflow-y-auto bg-bg-quiet px-4 py-4">
          <div v-for="msg in chat.messages.value" :key="msg.id" class="flex gap-2.5" :class="msg.role === 'user' ? 'flex-row-reverse' : ''">
            <div
              v-if="msg.role === 'bot'"
              class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink-primary text-[10px] font-semibold text-white"
            >
              AI
            </div>
            <div class="flex max-w-[78%] flex-col" :class="msg.role === 'user' ? 'items-end' : 'items-start'">
              <!-- 流式中：纯文本（自动转义）；结束后：安全的 Markdown -->
              <div
                v-if="msg.streaming && !msg.text"
                class="cs-typing rounded-2xl rounded-tl-md border border-line bg-bg px-4 py-3"
              >
                <span /><span /><span />
              </div>
              <div
                v-else-if="msg.streaming"
                class="whitespace-pre-line break-words rounded-2xl rounded-tl-md border border-line bg-bg px-3.5 py-2.5 text-base text-ink-body"
              >{{ msg.text }}</div>
              <div
                v-else
                class="cs-md break-words rounded-2xl rounded-tl-md px-3.5 py-2.5 text-base"
                :class="msg.error
                  ? 'border border-sale/30 bg-[#FFF5F4] text-sale'
                  : 'border border-line bg-bg text-ink-body'"
                v-html="renderMarkdown(msg.text)"
              />
              <!-- 元信息标签 -->
              <div v-if="metaTags(msg.meta).length" class="mt-1.5 flex flex-wrap gap-1.5">
                <span
                  v-for="(tag, i) in metaTags(msg.meta)"
                  :key="i"
                  class="rounded-pill px-2 py-0.5 text-2xs"
                  :class="tag.warn ? 'bg-[#FFF1EC] text-preorder' : 'bg-bg-tint text-ink-quiet'"
                >{{ tag.text }}</span>
              </div>
              <!-- 反馈 -->
              <div v-if="msg.role === 'bot' && !msg.streaming && !msg.error" class="mt-1 flex gap-1">
                <button
                  type="button"
                  class="rounded-pill px-2 py-0.5 text-2xs transition"
                  :class="msg.feedback === 1 ? 'bg-accent-soft text-accent' : 'text-ink-hint hover:bg-bg-tint hover:text-ink-quiet'"
                  :title="t('chat.helpful')"
                  :disabled="msg.feedback !== 0"
                  @click="handleRate(msg, 1)"
                >👍</button>
                <button
                  type="button"
                  class="rounded-pill px-2 py-0.5 text-2xs transition"
                  :class="msg.feedback === -1 ? 'bg-[#FFF1EC] text-preorder' : 'text-ink-hint hover:bg-bg-tint hover:text-ink-quiet'"
                  :title="t('chat.notHelpful')"
                  :disabled="msg.feedback !== 0"
                  @click="handleRate(msg, -1)"
                >👎</button>
              </div>
            </div>
          </div>

          <!-- 快捷提问 -->
          <div v-if="showSuggestions" class="flex flex-wrap gap-2 pt-1">
            <button
              v-for="s in suggestions"
              :key="s"
              type="button"
              class="rounded-pill border border-line bg-bg px-3 py-1.5 text-2xs text-ink-body transition hover:border-accent hover:text-accent"
              @click="pickSuggestion(s)"
            >{{ s }}</button>
          </div>
        </div>

        <!-- toast -->
        <div v-if="toast" class="px-4">
          <p class="rounded-lg bg-ink-primary/90 px-3 py-1.5 text-2xs text-white">{{ toast }}</p>
        </div>

        <!-- 输入区 -->
        <div class="border-t border-line bg-bg px-3 py-3">
          <div
            class="flex items-end gap-2 rounded-2xl border bg-bg px-2 py-1.5 transition"
            :class="asr.recording.value ? 'border-preorder' : 'border-line focus-within:border-ink-hint'"
          >
            <button
              v-if="asr.supported"
              type="button"
              class="shrink-0 rounded-full p-1.5 transition"
              :class="asr.recording.value
                ? 'bg-sale text-white animate-pulse'
                : asr.stopping.value
                  ? 'bg-bg-tint text-ink-hint'
                  : 'text-ink-quiet hover:bg-bg-tint hover:text-ink-primary'"
              :title="asr.stopping.value ? t('chat.transcribing') : asr.recording.value ? t('chat.micStop') : t('chat.micStart')"
              :aria-label="asr.stopping.value ? t('chat.transcribing') : asr.recording.value ? t('chat.micStop') : t('chat.micStart')"
              :disabled="asr.stopping.value"
              @click="toggleMic"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><path d="M12 17v4"/></svg>
            </button>
            <textarea
              ref="inputEl"
              v-model="draft"
              rows="1"
              class="cs-scroll max-h-[120px] flex-1 resize-none bg-transparent py-1 text-base text-ink-body outline-none placeholder:text-ink-hint"
              :placeholder="asr.recording.value ? t('chat.listening') : asr.stopping.value ? t('chat.transcribing') : t('chat.placeholder')"
              @input="onInput"
              @keydown.enter.exact.prevent="handleSend"
            />
            <button
              type="button"
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition disabled:cursor-not-allowed"
              :class="(!draft.trim() || chat.sending.value) ? 'bg-bg-tint text-ink-hint' : 'bg-accent text-white hover:bg-accent-hover'"
              :disabled="!draft.trim() || chat.sending.value"
              :aria-label="t('chat.send')"
              @click="handleSend"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 悬浮入口按钮 -->
    <button
      type="button"
      class="flex h-14 w-14 items-center justify-center rounded-full bg-ink-primary text-white shadow-[0_10px_30px_rgba(0,0,0,0.28)] transition hover:scale-105 active:scale-95"
      :aria-label="t('chat.open')"
      @click="togglePanel"
    >
      <svg v-if="!open" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 1 1 21 11.5z"/></svg>
      <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
    </button>
  </div>
</template>

<style scoped>
.cs-scroll::-webkit-scrollbar {
  width: 6px;
}
.cs-scroll::-webkit-scrollbar-thumb {
  background: #d2d2d7;
  border-radius: 999px;
}

/* 流式打字动画 */
.cs-typing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.cs-typing span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #9ca0a8;
  animation: cs-blink 1.2s infinite ease-in-out both;
}
.cs-typing span:nth-child(2) {
  animation-delay: 0.2s;
}
.cs-typing span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes cs-blink {
  0%, 80%, 100% { opacity: 0.25; }
  40% { opacity: 1; }
}

/* Markdown 内容（输入已先转义） */
.cs-md :deep(p) {
  margin: 0 0 6px;
}
.cs-md :deep(p:last-child),
.cs-md :deep(ul:last-child) {
  margin-bottom: 0;
}
.cs-md :deep(ul) {
  margin: 4px 0 6px;
  padding-left: 18px;
  list-style: disc;
}
.cs-md :deep(li) {
  margin: 2px 0;
}
.cs-md :deep(h1),
.cs-md :deep(h2),
.cs-md :deep(h3),
.cs-md :deep(h4) {
  font-weight: 600;
  margin: 6px 0 4px;
  line-height: 1.4;
}
.cs-md :deep(code) {
  background: #f5f5f7;
  border: 1px solid #e5e5e7;
  border-radius: 4px;
  padding: 1px 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}
.cs-md :deep(a) {
  color: #0071e3;
  text-decoration: none;
}
.cs-md :deep(a:hover) {
  text-decoration: underline;
}
</style>
