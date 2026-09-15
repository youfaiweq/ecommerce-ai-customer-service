/**
 * 客服后端 HTTP / SSE 客户端。
 *
 * 开发态所有请求走同源相对路径 `/api/...`，由 Vite 代理到 FastAPI（见 vite.config.ts）；
 * 生产态由反向代理把 `/api` 转发到后端即可，无需改代码。
 */
import type { ChatMeta, ChatProvider } from '@/types/chat'
import { authHeaders } from '@/lib/authApi'

const HTTP_BASE = '/api'

export interface HealthInfo {
  status: string
  app?: string
  version?: string
}

export async function checkHealth(signal?: AbortSignal): Promise<HealthInfo> {
  const r = await fetch(`${HTTP_BASE}/health`, { signal })
  if (!r.ok) throw new Error(`health HTTP ${r.status}`)
  return r.json()
}

function sessionUrl(path: string, sessionToken: string | null): string {
  if (!sessionToken) return `${HTTP_BASE}${path}`
  return `${HTTP_BASE}${path}?session_token=${encodeURIComponent(sessionToken)}`
}

export async function clearSession(sessionId: string, sessionToken: string | null): Promise<void> {
  try {
    await fetch(sessionUrl(`/chat/${encodeURIComponent(sessionId)}`, sessionToken), {
      method: 'DELETE',
      headers: authHeaders(),
    })
  } catch {
    /* 清空失败不阻塞前端重置 */
  }
}

export interface ChatHistoryResponse {
  session_id: string
  user_id?: string | null
  session_token?: string | null
  messages: Array<{ role: string; content: string }>
}

/** 刷新页面后恢复服务端保存的会话历史。 */
export async function getHistory(
  sessionId: string,
  sessionToken: string | null,
): Promise<ChatHistoryResponse> {
  const r = await fetch(sessionUrl(`/chat/${encodeURIComponent(sessionId)}`, sessionToken), {
    headers: authHeaders(),
  })
  if (!r.ok) throw new Error(`history HTTP ${r.status}`)
  return r.json()
}

export async function sendFeedback(
  sessionId: string,
  sessionToken: string | null,
  score: 1 | -1,
): Promise<void> {
  const r = await fetch(sessionUrl(`/chat/${encodeURIComponent(sessionId)}/feedback`, sessionToken), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ score }),
  })
  if (!r.ok) throw new Error(`feedback HTTP ${r.status}`)
}

export interface StreamHandlers {
  onMeta: (meta: ChatMeta) => void
  onDelta: (chunk: string) => void
}

/**
 * SSE 流式对话。后端事件序列：meta -> delta* -> done；异常时为 error。
 * 返回后端最终使用的 session_id（首次会话由后端生成，通过 meta 回传）。
 */
export async function streamChat(
  message: string,
  sessionId: string | null,
  sessionToken: string | null,
  provider: ChatProvider,
  { onMeta, onDelta }: StreamHandlers,
  signal?: AbortSignal,
): Promise<string | null> {
  const resp = await fetch(`${HTTP_BASE}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...authHeaders(),
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      session_token: sessionToken,
      provider,
    }),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`HTTP ${resp.status} ${detail}`.slice(0, 200))
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let resolvedSession = sessionId

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      try {
        const payload = JSON.parse(line.slice(5).trim()) as {
          event: string
          data: ChatMeta & { text?: string; message?: string }
        }
        if (payload.event === 'meta') {
          if (payload.data.session_id) resolvedSession = payload.data.session_id
          onMeta(payload.data)
        } else if (payload.event === 'delta') {
          onDelta(payload.data.text || '')
        } else if (payload.event === 'error') {
          throw new Error(payload.data.message || 'stream error')
        }
      } catch (err) {
        // 半条 JSON 导致的解析错误跳过；业务错误继续抛出
        if (err instanceof SyntaxError) continue
        throw err
      }
    }
  }
  return resolvedSession
}
