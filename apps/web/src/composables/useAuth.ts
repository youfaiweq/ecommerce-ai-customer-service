import { ref } from 'vue'
import type { AuthUser, LoginPayload, RegisterPayload } from '@/types/auth'
import { AuthError, fetchMe, login as apiLogin, logout as apiLogout, register as apiRegister, setStoredToken } from '@/lib/authApi'

/**
 * 鉴权状态机：当前用户、token、登录/登出、应用启动时回校验。
 *
 * 设计要点：
 *  - 全局单例（模块级 ref），组件直接消费同一份状态。
 *  - token 持久化到 localStorage，刷新页面后 `bootstrap()` 调 /auth/me 回填用户。
 *  - 登录成功后写入 token 与用户；登出时清空本地态并通知后端。
 *  - `ready` 标记首次 bootstrap 完成，便于路由守卫判断是否还在加载中。
 */
const user = ref<AuthUser | null>(null)
const token = ref<string | null>(null)
const ready = ref(false)
let bootstrapped = false

async function bootstrap(): Promise<void> {
  if (bootstrapped) return
  bootstrapped = true
  try {
    const me = await fetchMe()
    user.value = me
    token.value = localStorage.getItem('nora:auth:token:v1')
  } catch {
    setStoredToken(null)
    user.value = null
    token.value = null
  } finally {
    ready.value = true
  }
}

async function login(payload: LoginPayload): Promise<void> {
  const resp = await apiLogin(payload)
  setStoredToken(resp.token)
  token.value = resp.token
  user.value = resp.user
}

async function register(payload: RegisterPayload): Promise<void> {
  const resp = await apiRegister(payload)
  setStoredToken(resp.token)
  token.value = resp.token
  user.value = resp.user
}

async function logout(): Promise<void> {
  await apiLogout()
  setStoredToken(null)
  token.value = null
  user.value = null
}

export function useAuth() {
  return {
    user,
    token,
    ready,
    bootstrap,
    login,
    register,
    logout,
  }
}

export { AuthError }
