/** 客服会话相关类型，字段与后端 app/api/chat.py 的响应契约对齐。 */

export interface ChatIntent {
  intent?: string
  label?: string
  confidence?: number
  method?: string
}

export interface ChatSource {
  id: string
  category?: string
  question?: string
  score?: number
}

/** 仅允许切换后端预设服务商；浏览器不持有任何模型 API Key。 */
export type ChatProvider = 'deepseek' | 'ollama'

/** SSE meta 事件携带的元信息。 */
export interface ChatMeta {
  session_id?: string
  session_token?: string | null
  provider?: ChatProvider
  intent?: ChatIntent
  sources?: ChatSource[]
  transferred?: boolean
  grounded?: boolean
  order_no?: string | null
  order_found?: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'bot'
  text: string
  meta?: ChatMeta
  /** 0=未反馈 1=👍 -1=👎 */
  feedback: 0 | 1 | -1
  streaming?: boolean
  error?: boolean
}

export type ConnectionState = 'connecting' | 'online' | 'offline'
