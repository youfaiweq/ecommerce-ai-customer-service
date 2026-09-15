import { onBeforeUnmount, ref } from 'vue'
import { getStoredToken } from '@/lib/authApi'

/**
 * 流式离线 ASR：MediaRecorder 采集 → WebSocket `/asr/stream` 边录边识别。
 * 协议与后端 app/api/audio.py 对齐：
 *   客户端：{event:'start'} 首帧 → 二进制音频帧 → {event:'stop'}
 *   服务端：ready / partial / final / error / closed
 */

export interface AsrStartOptions {
  sessionId: string | null
  onPartial: (text: string) => void
  onFinal: (text: string, durationS?: number) => void
  onError: (message: string) => void
  onStateChange?: (recording: boolean) => void
}

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/asr/stream`
}

function pickMime(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', '']
  for (const m of candidates) {
    if (m === '' || window.MediaRecorder.isTypeSupported(m)) return m
  }
  return ''
}

export function useAsr() {
  const supported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    typeof window.MediaRecorder === 'function' &&
    typeof window.WebSocket === 'function'

  const recording = ref(false)
  // 已停止采集、正在等待服务端处理最后一段音频；此时不能再开一条新录音。
  const stopping = ref(false)
  const partial = ref('')

  let socket: WebSocket | null = null
  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let finalized = false
  let active = false
  let opts: AsrStartOptions | null = null

  function stopTracks() {
    stream?.getTracks().forEach((t) => t.stop())
  }

  function cleanup() {
    stopTracks()
    stream = null
    recorder = null
    socket = null
    active = false
    recording.value = false
    stopping.value = false
    opts?.onStateChange?.(false)
  }

  function sendStopSignal() {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ event: 'stop' }))
  }

  async function start(options: AsrStartOptions) {
    if (!supported || active) return
    active = true
    opts = options
    finalized = false
    partial.value = ''

    const ws = new WebSocket(wsUrl())
    socket = ws

    try {
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(() => reject(new Error('WS 连接超时（10s）')), 10000)
        ws.addEventListener('open', () => {
          window.clearTimeout(timer)
          ws.send(
            JSON.stringify({
              event: 'start',
              sample_rate: 16000,
              language: 'auto',
              session_id: options.sessionId,
              token: getStoredToken(),
              partial_interval_ms: 600,
            }),
          )
          resolve()
        })
        ws.addEventListener('error', () => {
          window.clearTimeout(timer)
          reject(new Error('无法连接语音识别服务，请确认后端已启用 ASR'))
        })
      })
    } catch (e) {
      closeSocket()
      cleanup()
      throw e
    }

    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: { event?: string; text?: string; code?: string; message?: string; duration_s?: number }
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      if (msg.event === 'partial') {
        partial.value = msg.text || ''
        options.onPartial(partial.value)
      } else if (msg.event === 'final') {
        finalized = true
        const text = (msg.text || '').trim()
        cleanup()
        options.onFinal(text, msg.duration_s)
      } else if (msg.event === 'error') {
        options.onError(msg.message || msg.code || '识别失败')
      }
    }

    ws.onclose = () => {
      if (!finalized && active) {
        cleanup()
        options.onError('语音识别连接中断，请重试')
      }
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      })
    } catch (e) {
      closeSocket()
      cleanup()
      throw new Error(`无法访问麦克风：${(e as Error).message || (e as Error).name}`)
    }

    const mime = pickMime()
    try {
      recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
    } catch (e) {
      closeSocket()
      cleanup()
      throw new Error(`创建录音器失败：${(e as Error).message}`)
    }

    recorder.ondataavailable = (e: BlobEvent) => {
      if (!e.data || e.data.size === 0) return
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(e.data)
    }
    // stop() 后 MediaRecorder 会先派发最后一段 dataavailable，再派发 stop。
    // 因此在这里才通知服务端结束，可避免把最后一句语音截断。
    recorder.onstop = sendStopSignal

    recorder.start(250)
    recording.value = true
    options.onStateChange?.(true)
  }

  function stop() {
    if (!active || stopping.value) return
    stopping.value = true
    // 立即更新界面并释放浏览器麦克风；转写结果仍会在 final 事件抵达后填回输入框。
    recording.value = false
    opts?.onStateChange?.(false)
    const activeRecorder = recorder
    if (activeRecorder && activeRecorder.state !== 'inactive') activeRecorder.stop()
    else sendStopSignal()
    stopTracks()
  }

  function closeSocket() {
    if (socket) {
      try {
        if (socket.readyState === WebSocket.OPEN) socket.close(1000, 'client-stop')
      } catch {
        /* ignore */
      }
      socket = null
    }
  }

  onBeforeUnmount(() => {
    try {
      stop()
    } catch {
      /* ignore */
    }
    closeSocket()
    cleanup()
  })

  return { supported, recording, stopping, partial, start, stop }
}
