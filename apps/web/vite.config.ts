import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// 后端开发端口（npm run dev:api）。Docker / 裸跑 uvicorn 默认 8000。
// 不使用 node:url / process，避免额外依赖 @types/node；运行时由 Vite(Node) 执行。
const API_TARGET = 'http://127.0.0.1:8002'

/** 把 new URL(...) 转成本地文件路径（兼容 Windows 盘符），等价于 fileURLToPath。 */
function toPath(url: URL): string {
  return decodeURIComponent(url.pathname.replace(/^\/([a-zA-Z]:)/, '$1'))
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': toPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 允许 dev server 读取 monorepo 内其它 workspace 的文件
    // （前端 mock 直接引用后端 data/products.json 作为单一数据源）
    fs: {
      allow: [toPath(new URL('../../', import.meta.url))],
    },
    proxy: {
      // HTTP 接口：把 /api 前缀代理到 FastAPI，并去掉 /api
      // 例：/api/chat/stream -> http://127.0.0.1:8001/chat/stream
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // 流式 ASR：后端 WS 端点是 /asr/stream（不带 /api 前缀）
      '/asr': {
        target: API_TARGET,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    clearMocks: true,
  },
})
