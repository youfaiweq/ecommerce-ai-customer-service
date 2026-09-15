/** 鉴权相关类型，字段与后端 app/api/auth.py 的响应契约对齐。 */

/** 登录请求体。 */
export interface LoginPayload {
  user_id: string
  password: string
}

export interface RegisterPayload extends LoginPayload {
  name: string
  email?: string
}

/** 脱敏用户信息。 */
export interface AuthUser {
  user_id: string
  name?: string | null
  email?: string | null
  created_at?: string | null
}

/** 登录成功响应。 */
export interface LoginResponse {
  token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

/** 鉴权状态机对外暴露的只读状态。 */
export interface AuthState {
  user: AuthUser | null
  token: string | null
  ready: boolean
}
