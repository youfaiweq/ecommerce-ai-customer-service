/** 后端 API 基础 URL。
 * 开发时 vite 把 /api 代理到 127.0.0.1:8000，所以留空字符串走同源代理。
 * 生产可改成 https://api.example.com。
 */
import { authHeaders } from '@/lib/authApi'

const API_BASE = ''

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(),
    signal,
  })
  if (!r.ok) {
    throw new Error(`API ${path} -> HTTP ${r.status}`)
  }
  return r.json() as Promise<T>
}
