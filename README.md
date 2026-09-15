# NORA Store · monorepo

> Apple-informed 极简 3C 电商：Vue 3 前端门店 + FastAPI AI 客服后端，全部纳入 npm workspaces。

## 结构

```
nora-store/                              ← 本仓库
├── package.json                         # workspace 根
├── apps/
│   └── web/                              # @nora/web  Vue 3 + Vite + Pinia + Tailwind
│       ├── src/
│       ├── package.json
│       └── ...
└── ecommerce-ai-customer-service/        # @nora/api  FastAPI + 离线 ASR
    ├── app/
    ├── frontend/                         # 旧版测试聊天 UI（保留，不用）
    └── package.json
```

## 一键启动

```bash
# 一次性：在 monorepo 根目录安装所有 workspace 依赖
npm install

# 同时启动后端 + 前端，彩色日志分流
npm run dev
```

打开 [http://127.0.0.1:5173/](http://127.0.0.1:5173/) 看 Vue 门店。

### 端口说明

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| Vue 门店 | http://127.0.0.1:5173 | Vite dev server |
| FastAPI 后端（monorepo 开发） | http://127.0.0.1:8001 | `npm run dev:api`，为避开本机占用的 8000 而偏移 |
| FastAPI 后端（裸跑 uvicorn / Docker） | http://127.0.0.1:8000 | 见后端 README / docker-compose |

前端通过 Vite 代理把 `/api/*`（去前缀）与 `/asr/*`（WebSocket）转发到 `127.0.0.1:8001`，
配置见 `apps/web/vite.config.ts`，代码里始终用同源相对路径，无需写死后端地址。

仅前端：
```bash
npm run dev:web
```

仅后端（含 ASR）：
```bash
npm run dev:api:asr       # 注意：要先 .venv/Scripts/python.exe -m pip install -r requirements-asr.txt
npm run dev:api           # 不含 ASR
```

## 已打通的前后端能力

- **商品**：`stores/products.ts` 从后端 `/api/products` 拉取，后端不可用时降级到本地数据；
  前端兜底数据直接引用后端 `data/products.json`（单一数据源，不再手工双写）。
- **AI 客服**：全站右下角浮动客服窗（`components/ChatWidget.vue`），支持
  SSE 流式对话、意图/引用/订单标签、👍/👎 反馈、清空、快捷提问，以及 🎙️ WebSocket 流式语音识别。
  语音需以 ASR 模式启动后端（`dev:api:asr`）；非 ASR 模式下聊天仍可用，麦克风会提示错误。
- **登录态鉴权**：演示账号 + HMAC-SHA256 自签名 token（stateless）。
  - `/auth/login`、`/auth/me`、`/auth/logout` 三接口；密码以 PBKDF2-HMAC-SHA256（100k 迭代）哈希存储。
  - `/orders` 与 `/orders/{no}` **强制鉴权**并校验订单归属（跨用户访问返回 403 `order_forbidden`）。
  - `/chat` 与 `/chat/stream` **可选鉴权**：携带 token 时由后端把 `user_id` 绑定到 dialogue 会话与日志表，未登录仍可匿名使用。
  - 前端：`/login` + `/account` 路由、路由守卫（`requiresAuth` / `guestOnly`）、`useAuth` 单例状态机、`authHeaders()` 自动注入到 `apiGet` 与 `streamChat`。
  - 演示账号：`u1001` 张伟 / `u1002` 王芳 / `u1003` 李娜 / `u1004` 陈晨，默认密码 `demo123456`（见 `data/users.json`）。

## 设计语言

Apple-informed mono-chrome（前面"3C 极简电商 · 设计系统"定的）：

- **主色**：Ink `#0A0A0A` · Body `#1D1D1F` · Quiet `#6E6E73`
- **表面**：Surface `#FFFFFF` · Tint `#F5F5F7` · Border `#E5E5E7`
- **强调**：Blue `#0071E3`（价格/CTA/SKU） · Sale `#FF3B30` · Stock `#34C759`
- **字体**：Inter (display + body) · JetBrains Mono (SKU)
- **圆角**：4 / 8 / 16 / pill(999)
- **阴影**：none，用 0.5px border 代替

## 测试

后端 `pytest` 共 **298** 用例，覆盖 token 签发/校验、登录/查我/登出、订单归属校验、会话用户绑定、SSE 流式与统一错误处理等。前端 `vue-tsc -b && vite build` 通过类型检查与生产构建。

```bash
cd ecommerce-ai-customer-service && .venv/Scripts/python.exe -m pytest      # 后端 298 用例
cd apps/web && npm run build                                                  # 前端类型 + 构建
```

## 后续路径

- 商品接口已接通；可加分页 / 筛选 / 详情 SSR
- 加入 Stripe / 微信支付
- 进入 i18n 模式（客服回复目前以后端语言为准，UI 已支持中英切换）
- 接 3D 产品 viewer（`<model-viewer>` 或 three.js）
- token 黑名单：当前登出仅前端丢弃 token，将来可接 Redis 把 `jti` 写黑名单

## License

Internal / private.
