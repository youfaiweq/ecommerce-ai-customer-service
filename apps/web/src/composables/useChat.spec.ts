import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  clearSession: vi.fn(),
  sendFeedback: vi.fn(),
  getHistory: vi.fn(),
}))

vi.mock('@/lib/chatApi', () => ({
  checkHealth: vi.fn(),
  clearSession: mocks.clearSession,
  sendFeedback: mocks.sendFeedback,
  getHistory: mocks.getHistory,
  streamChat: mocks.streamChat,
}))

import { useChat } from './useChat'

describe('useChat', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.streamChat.mockReset()
    mocks.clearSession.mockReset()
    mocks.sendFeedback.mockReset()
    mocks.getHistory.mockReset()
  })

  it('persists the anonymous session credential returned by the stream', async () => {
    mocks.streamChat.mockImplementation(async (_message, _sessionId, _sessionToken, _provider, handlers) => {
      handlers.onMeta({ session_id: 'session-1', session_token: 'secret-1' })
      handlers.onDelta('你好')
      return 'session-1'
    })

    const chat = useChat()
    await chat.send('你好')

    expect(mocks.streamChat).toHaveBeenCalledWith('你好', null, null, 'deepseek', expect.any(Object))
    expect(chat.sessionId.value).toBe('session-1')
    expect(chat.sessionToken.value).toBe('secret-1')
    expect(localStorage.getItem('nora:chat:session-token:v1')).toBe('secret-1')
  })

  it('persists the chosen model provider for the next chat session', () => {
    const chat = useChat()
    chat.setProvider('ollama')

    expect(chat.provider.value).toBe('ollama')
    expect(localStorage.getItem('nora:chat:provider:v1')).toBe('ollama')
  })

  it('restores saved conversation history after a page refresh', async () => {
    localStorage.setItem('nora:chat:session:v1', 'session-restore')
    localStorage.setItem('nora:chat:session-token:v1', 'anonymous-token-123456')
    mocks.getHistory.mockResolvedValue({
      session_id: 'session-restore',
      session_token: 'anonymous-token-123456',
      messages: [
        { role: 'user', content: '我的订单到哪了？' },
        { role: 'assistant', content: '我来帮您查询物流。' },
      ],
    })

    const chat = useChat()
    await chat.restore('欢迎回来')

    expect(mocks.getHistory).toHaveBeenCalledWith('session-restore', 'anonymous-token-123456')
    expect(chat.messages.value.map((message) => [message.role, message.text])).toEqual([
      ['user', '我的订单到哪了？'],
      ['bot', '我来帮您查询物流。'],
    ])
  })
})
