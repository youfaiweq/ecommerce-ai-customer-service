/**
 * 鉴权后端 HTTP 客户端。
 *
 * 与 chatApi.ts 一致，开发态走同源相对路径 `/api/auth/...`，由 Vite 代理到 FastAPI。
 * 生产态由反向代理转发即可。
 */
import type { AuthUser, LoginPayload, LoginResponse, RegisterPayload } from '@/types/auth'

const HTTP_BASE = '/api'

/** 从 localStorage 取 token，供 fetch 注入 Authorization 头。 */
export function getStoredToken(): string | null {
  try {
    return localStorage.getItem('nora:auth:token:v1')
  } catch {
    return null
  }
}

/** 写入 / 清除 token，供 useAuth composable 调用。 */
export function setStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem('nora:auth:token:v1', token)
    else localStorage.removeItem('nora:auth:token:v1')
  } catch {
    /* 隐私模式下忽略持久化失败 */
  }
}

/** 构造鉴权请求头；未登录时返回空对象。 */
export function authHeaders(): Record<string, string> {
  const token = getStoredToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 账号密码换取 token。 */
export async function login(payload: LoginPayload): Promise<LoginResponse> {
  const r = await fetch(`${HTTP_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => null)
    const code = detail?.error?.code ?? `http_${r.status}`
    const message = detail?.error?.message ?? `HTTP ${r.status}`
    throw new AuthError(code, message)
  }
  return r.json()
}

export async function register(payload: RegisterPayload): Promise<LoginResponse> {
  const r = await fetch(`${HTTP_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => null)
    throw new AuthError(detail?.error?.code ?? `http_${r.status}`, detail?.error?.message ?? `HTTP ${r.status}`)
  }
  return r.json()
}

/** 凭 token 查看当前登录用户；token 无效或过期抛 AuthError。 */
export async function fetchMe(): Promise<AuthUser> {
  const r = await fetch(`${HTTP_BASE}/auth/me`, {
    headers: authHeaders(),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => null)
    const code = detail?.error?.code ?? `http_${r.status}`
    const message = detail?.error?.message ?? `HTTP ${r.status}`
    throw new AuthError(code, message)
  }
  return r.json()
}

/** 登出；stateless token，后端仅返回 204，客户端丢弃 token 即完成。 */
export async function logout(): Promise<void> {
  try {
    await fetch(`${HTTP_BASE}/auth/logout`, {
      method: 'POST',
      headers: authHeaders(),
    })
  } catch {
    /* 网络失败不阻塞前端清理本地态 */
  }
}

/** 鉴权失败异常，携带后端错误码便于 UI 分支处理。 */
export class AuthError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.name = 'AuthError'
    this.code = code
  }
}
