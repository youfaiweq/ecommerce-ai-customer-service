import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { useAsr } from './useAsr'

const trackStop = vi.fn()
const sockets: FakeWebSocket[] = []

class FakeWebSocket extends EventTarget {
  static OPEN = 1
  readyState = FakeWebSocket.OPEN
  sent: unknown[] = []

  constructor(_url: string) {
    super()
    sockets.push(this)
    queueMicrotask(() => this.dispatchEvent(new Event('open')))
  }

  send(value: unknown) {
    this.sent.push(value)
  }

  close() {
    this.readyState = 3
    this.dispatchEvent(new Event('close'))
  }
}

class FakeMediaRecorder {
  static isTypeSupported() {
    return true
  }

  state: RecordingState = 'inactive'
  ondataavailable: ((event: BlobEvent) => void) | null = null
  onstop: (() => void) | null = null

  constructor(_stream: MediaStream, _options?: MediaRecorderOptions) {}

  start() {
    this.state = 'recording'
  }

  stop() {
    this.state = 'inactive'
    // 浏览器的事件顺序：先给最后的音频块，再通知停止。
    this.ondataavailable?.({ data: new Blob(['tail']) } as BlobEvent)
    this.onstop?.()
  }
}

describe('useAsr', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    sockets.length = 0
    trackStop.mockReset()
  })

  it('stops microphone and UI immediately, then sends stop after the final audio chunk', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: trackStop }],
        }),
      },
    })

    let asr!: ReturnType<typeof useAsr>
    const wrapper = mount(defineComponent({
      setup() {
        asr = useAsr()
        return () => null
      },
    }))
    await asr.start({
      sessionId: null,
      onPartial: vi.fn(),
      onFinal: vi.fn(),
      onError: vi.fn(),
    })

    asr.stop()

    expect(asr.recording.value).toBe(false)
    expect(asr.stopping.value).toBe(true)
    expect(trackStop).toHaveBeenCalledOnce()
    expect(sockets[0].sent[sockets[0].sent.length - 1]).toBe(JSON.stringify({ event: 'stop' }))
    wrapper.unmount()
  })
})
