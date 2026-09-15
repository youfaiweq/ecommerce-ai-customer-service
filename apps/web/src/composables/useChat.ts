import { ref } from 'vue'
import type { ChatMessage, ChatMeta, ChatProvider, ConnectionState } from '@/types/chat'
import { checkHealth, clearSession, getHistory, sendFeedback, streamChat } from '@/lib/chatApi'

const SESSION_KEY = 'nora:chat:session:v1'
const SESSION_TOKEN_KEY = 'nora:chat:session-token:v1'
const PROVIDER_KEY = 'nora:chat:provider:v1'

let seq = 0
function nextId(): string {
  seq += 1
  return `m${Date.now().toString(36)}-${seq}`
}

/**
 * 客服会话状态机：消息列表、session 持久化、SSE 发送、反馈、清空、连接状态。
 * 通过工厂函数创建，组件卸载即释放；session_id 存 localStorage 以延续多轮上下文。
 */
export function useChat() {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | null>(
    typeof localStorage !== 'undefined' ? localStorage.getItem(SESSION_KEY) : null,
  )
  const sessionToken = ref<string | null>(
    typeof localStorage !== 'undefined' ? localStorage.getItem(SESSION_TOKEN_KEY) : null,
  )
  const storedProvider = typeof localStorage !== 'undefined' ? localStorage.getItem(PROVIDER_KEY) : null
  const provider = ref<ChatProvider>(storedProvider === 'ollama' ? 'ollama' : 'deepseek')
  const connection = ref<ConnectionState>('connecting')
  const sending = ref(false)
  const restoring = ref(false)

  function persistSession(id: string | null, token: string | null = sessionToken.value) {
    sessionId.value = id
    sessionToken.value = token
    if (typeof localStorage === 'undefined') return
    if (id) localStorage.setItem(SESSION_KEY, id)
    else localStorage.removeItem(SESSION_KEY)
    if (token) localStorage.setItem(SESSION_TOKEN_KEY, token)
    else localStorage.removeItem(SESSION_TOKEN_KEY)
  }

  function addMessage(msg: Omit<ChatMessage, 'id' | 'feedback'> & { feedback?: 0 | 1 | -1 }) {
    messages.value.push({ id: nextId(), feedback: 0, ...msg })
  }

  function setProvider(next: ChatProvider) {
    provider.value = next
    if (typeof localStorage !== 'undefined') localStorage.setItem(PROVIDER_KEY, next)
  }

  async function refreshHealth() {
    connection.value = 'connecting'
    try {
      await checkHealth()
      connection.value = 'online'
    } catch {
      connection.value = 'offline'
    }
  }

  async function restore(greeting: string) {
    if (messages.value.length || restoring.value) return
    const savedSessionId = sessionId.value
    if (!savedSessionId) {
      addMessage({ role: 'bot', text: greeting })
      return
    }

    restoring.value = true
    try {
      const history = await getHistory(savedSessionId, sessionToken.value)
      // 匿名会话凭证只在服务端首次签发/恢复时回传；登录会话保持 null。
      persistSession(history.session_id, history.session_token || sessionToken.value)
      messages.value = history.messages
        .filter((message) => (message.role === 'user' || message.role === 'assistant') && message.content)
        .map((message) => ({
          id: nextId(),
          role: message.role === 'user' ? 'user' : 'bot',
          text: message.content,
          feedback: 0,
        }))
      if (!messages.value.length) addMessage({ role: 'bot', text: greeting })
      connection.value = 'online'
    } catch (err) {
      // 只有会话不存在/凭证失效才丢弃本地指针；网络暂时不可用时保留，避免刷新导致永久丢失。
      if (/history HTTP (403|404)/.test((err as Error).message)) persistSession(null, null)
      messages.value = [{ id: nextId(), role: 'bot', text: greeting, feedback: 0 }]
    } finally {
      restoring.value = false
    }
  }

  async function send(text: string) {
    const content = text.trim()
    if (!content || sending.value) return
    sending.value = true

    addMessage({ role: 'user', text: content })
    // 从响应式数组中取回代理对象再做流式增量修改（直接改原始对象不会触发更新）
    messages.value.push({ id: nextId(), role: 'bot', text: '', feedback: 0, streaming: true })
    const bot = messages.value[messages.value.length - 1]

    try {
      const sid = await streamChat(content, sessionId.value, sessionToken.value, provider.value, {
        onMeta: (meta: ChatMeta) => {
          if (meta.session_id) persistSession(meta.session_id, meta.session_token || null)
          bot.meta = meta
        },
        onDelta: (chunk) => {
          bot.text += chunk
        },
      })
      if (sid) persistSession(sid)
      bot.streaming = false
      if (!bot.text) bot.text = '（无回复）'
      connection.value = 'online'
    } catch (err) {
      bot.streaming = false
      bot.error = true
      bot.text = `请求失败：${(err as Error).message}\n请确认客服服务已启动。`
      connection.value = 'offline'
    } finally {
      sending.value = false
    }
  }

  async function rate(msg: ChatMessage, score: 1 | -1) {
    if (!sessionId.value || msg.feedback !== 0) return
    // 乐观更新，失败回滚并抛出，由组件提示
    const prev = msg.feedback
    msg.feedback = score
    try {
      await sendFeedback(sessionId.value, sessionToken.value, score)
    } catch (e) {
      msg.feedback = prev
      throw e
    }
  }

  async function clear(greeting: string) {
    if (sessionId.value) await clearSession(sessionId.value, sessionToken.value)
    persistSession(null, null)
    messages.value = [{ id: nextId(), role: 'bot', text: greeting, feedback: 0 }]
  }

  return {
    messages,
    sessionId,
    sessionToken,
    restoring,
    provider,
    connection,
    sending,
    addMessage,
    setProvider,
    refreshHealth,
    restore,
    send,
    rate,
    clear,
  }
}
