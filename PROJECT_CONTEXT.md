# NORA Store 项目上下文

NORA Store 是一个 3C 数码电商演示项目，由两个 npm workspace 组成：Vue 3 门店前端与 FastAPI AI 客服后端。前端在 `http://127.0.0.1:5173`，后端在 monorepo 开发模式下跑 `http://127.0.0.1:8001`，前端通过 Vite 代理把 `/api/*` 转发到后端，代码里始终写同源相对路径，不写死后端地址。

## 顶层结构

```
net_shop/                              # 仓库根，npm workspaces
├── package.json                       # workspace 根，dev = concurrently(api + web)
├── apps/
│   └── web/                           # @nora/web   Vue 3 + Vite + Pinia + Tailwind
└── ecommerce-ai-customer-service/     # @nora/api   FastAPI + 可选离线 ASR
    ├── app/                           # 后端源码
    ├── data/                          # JSON 业务数据 + SQLite 日志库
    ├── tests/                         # 298 个 pytest 用例
    ├── frontend/                      # 旧版零构建聊天页，保留但不再使用
    └── .venv/                         # Python 虚拟环境，独立维护于 node_modules 之外
```

## 技术栈

| 层 | 技术 | 版本 |
| --- | --- | --- |
| 前端框架 | Vue 3 + Vite + TypeScript | 3.5 / 6.0 / 5.7 |
| 前端状态与路由 | Pinia / vue-router / vue-i18n | 2.2 / 4.5 / 11 |
| 前端样式 | Tailwind CSS + PostCSS | 3.4 |
| 后端框架 | FastAPI + Uvicorn | fastapi>=0.110 |
| 配置与模型 | pydantic v2 + pydantic-settings | >=2.6 / >=2.2 |
| 大模型接入 | openai SDK（OpenAI 兼容协议） | >=1.30 |
| 会话日志 | sqlite3 标准库 + asyncio.Queue 后台批写 | 无额外依赖 |
| 语音识别 | faster-whisper（可选，默认不装） | requirements-asr.txt |
| 后端测试 | pytest | 298 用例 / 23 文件 |
| 代码检查 | ruff（target py312，line-length 100） | E/F/W/I/B/UP |

Python 要求 3.10 以上，当前开发环境为 3.13。

## 系统边界与端口

| 服务 | 地址 | 启动方式 |
| --- | --- | --- |
| Vue 门店 | http://127.0.0.1:5173 | `npm run dev:web` |
| FastAPI（monorepo 开发） | http://127.0.0.1:8001 | `npm run dev:api` 或 `npm run dev:api:asr` |
| FastAPI（裸跑 uvicorn / Docker） | http://127.0.0.1:8000 | `uvicorn app.main:app --reload` |

端口偏移的原因是本机 8000 常被占用，monorepo 脚本固定使用 8001。Vite 代理规则定义在 `apps/web/vite.config.ts`：`/api` 转发到 8001 并去掉前缀，`/asr` 转发到 8001 且开启 WebSocket。

## 关键入口文件

| 要改什么 | 去哪里 |
| --- | --- |
| 服务装配、中间件、lifespan | `ecommerce-ai-customer-service/app/main.py` |
| 新增 HTTP 接口 | `app/api/*.py` |
| 对话编排主流程 | `app/services/chat_service.py` |
| 意图规则与兜底分类 | `app/services/intent_service.py` |
| 订单号提取 / 订单查询 / 物流格式化 | `app/services/order_service.py` |
| FAQ 索引与检索 | `app/services/knowledge_base.py`、`app/services/retriever.py` |
| 模型调用、重试与熔断 | `app/services/llm_service.py` |
| 会话内存历史与槽位 | `app/services/dialogue_manager.py` |
| SQLite 落库与统计 | `app/services/log_store.py` |
| 鉴权 token 与用户校验 | `app/auth/tokens.py`、`app/auth/users.py`、`app/auth/dependencies.py` |
| 配置项定义 | `app/config.py`（配合 `.env`） |
| 前端路由与守卫 | `apps/web/src/router/index.ts` |
| 前端客服浮窗 | `apps/web/src/components/ChatWidget.vue` |
| 前端 SSE / 鉴权客户端 | `apps/web/src/lib/chatApi.ts`、`apps/web/src/lib/authApi.ts` |
| 前端登录态 | `apps/web/src/composables/useAuth.ts` |
| 商品数据与兜底 | `apps/web/src/stores/products.ts`、`apps/web/src/data/products.ts` |

## 对话主链路

核心编排在 `app/services/chat_service.py`，顺序为七步：意图识别 → 业务数据查询 → 知识库检索 → 组装 Prompt → 大模型生成 → 转人工判定 → 持久化。

意图识别覆盖查询订单、查询物流、退换货、商品咨询、优惠活动、转人工、其他共 7 类，策略是规则关键词优先，未命中再调大模型兜底（`INTENT_USE_LLM` 控制）。约八成高频请求走规则命中，不消耗 token。

订单号从用户消息中正则提取，支持精确、后缀、包含三级匹配（`202609030002`、`0002`、`123456` 均可命中），并排除手机号避免误识别；本轮未提取到时回退到会话槽位，因此「那物流到哪了」这类追问能自动复用上一轮订单号，命中后写回槽位。结构化订单与物流数据会注入 Prompt，让模型基于真实数据作答以抑制幻觉。

知识库对 `data/faq.json` 的 20 条 FAQ 建索引，检索 top-k（默认 3）且得分低于 `FAQ_MIN_SCORE`（默认 0.15）视为未命中。转人工判定有两条路径：意图命中转人工时直接返回、不调用大模型；模型回复含不确定措辞时追加转人工提示。

## 接口清单

后端共 28 个 HTTP 路径与 1 个 WebSocket 端点。

| 分组 | 接口 |
| --- | --- |
| 对话 | `POST /chat`、`POST /chat/stream`（SSE）、`GET /chat/{session_id}`、`DELETE /chat/{session_id}`、`POST /chat/{session_id}/feedback` |
| 语音 | `POST /chat/audio`、`GET /asr/status`、`WS /asr/stream` |
| 知识库 | `GET /knowledge/search`、`GET /knowledge/stats`、`POST /knowledge/reload` |
| 订单 | `GET /orders`、`GET /orders/{order_no}` |
| 商品 | `GET /products`、`GET /products/`、`GET /products/{product_id}` |
| 鉴权 | `POST /auth/login`、`GET /auth/me`、`POST /auth/logout` |
| 管理 | `GET /admin/sessions`、`GET /admin/sessions/{session_id}`、`GET /admin/sessions/{session_id}/export`、`DELETE /admin/sessions/{session_id}`、`GET /admin/sessions/{session_id}/feedback`、`GET /admin/search`、`GET /admin/stats`、`POST /admin/feedback`、`GET /admin/feedback/stats` |
| 运维 | `GET /`、`GET /health`、`GET /health/deep` |

SSE 事件序列固定为 `meta` 到多次 `delta` 再到 `done`，异常时是 `error`。`meta` 携带 `session_id`、`intent`、`sources`、`user_id`。前端在 `apps/web/src/lib/chatApi.ts` 用 `fetch` 加 `ReadableStream` 手工解析，没有用 `EventSource`，因为需要 POST 与自定义请求头。

`/admin/*` 在设置了 `ADMIN_API_KEY` 或 `ADMIN_API_KEYS` 后必须带 `X-Admin-Key` 请求头，留空则不校验。

## 鉴权机制

token 是服务端自签的 HMAC-SHA256 无状态令牌，payload 为 `{user_id, exp, jti}`，只用标准库的 `hmac`、`hashlib`、`json`、`base64`、`secrets` 实现，没有引入 PyJWT。默认有效期 86400 秒。服务端不保存 session，登出接口返回 204，仅用于前端语义清晰，未来接 token 黑名单的扩展点在 `app/api/auth.py` 的 `logout`。

密码用 `hashlib.pbkdf2_hmac` 加 100k 迭代校验，同样零新依赖。演示账号 4 个：`u1001` 张伟、`u1002` 王芳、`u1003` 李娜、`u1004` 陈晨，密码统一 `demo123456`，数据在 `data/users.json`。

鉴权强度按接口区分：订单接口强制鉴权，未带或无效 token 返回 401，跨用户访问返回 403 且 error code 为 `order_forbidden`；对话接口为可选鉴权，登录后把 `user_id` 绑定到会话与日志，未登录仍可匿名使用。前端把 token 放在 `localStorage` 的 `nora:auth:token:v1`，`authHeaders()` 自动注入到 `apiGet` 与 `streamChat`，`useAuth` 是模块级单例状态机，路由守卫用 `requiresAuth` 与 `guestOnly` 两个 meta 标记。

## 数据与存储

业务数据全部是 JSON 文件，无需数据库：`data/products.json` 6 个商品、`data/orders.json` 8 个订单（含商品明细与物流轨迹）、`data/faq.json` 20 条 FAQ、`data/users.json` 4 个演示账号。

会话日志可选落库到 SQLite 的 `data/app.db`，`LOG_STORE_ENABLED` 控制开关，关闭后管理接口返回空数据。表结构为 `sessions`（会话汇总、消息数、最近意图、转人工次数、`user_id`）与 `messages`（每条消息含角色、内容、意图、引用来源 JSON、订单号、是否命中知识库、是否转人工），另有 `feedback` 表存正负反馈。写路径走 `asyncio.Queue` 后台批写（50 条或 500ms 触发），请求路径不阻塞；SQLite 开了 WAL、`synchronous=NORMAL`、64MB 页缓存与 256MB mmap。

服务重启时会从 SQLite 把最近活跃会话回填到内存的 DialogueManager，逻辑在 `app/main.py` 的 lifespan 里。内存侧单会话保留最近 20 条历史，超出按 LRU 淘汰旧会话；历史超过阈值（`context_summary_trigger` 默认 16 条）时调大模型把早期对话压成一句 200 字摘要，每个会话最多压一次。

## 配置规则

配置由 `app/config.py` 的 `Settings` 定义，pydantic-settings 从环境变量与 `.env` 读取。字段名与环境变量名大小写不敏感对应，另有别名兼容：`OPENAI_API_KEY` 同时接受 `DEEPSEEK_API_KEY`。

需要特别注意的覆盖关系：`.env` 的值会覆盖代码里的默认值。例如 `config.py` 中 `version` 默认是 `0.7.0`，`.env` 里也有 `VERSION=0.7.0`，只改代码而不改 `.env` 不会生效。改版本号、端口、开关这类字段时要同时检查两处。

常改的变量：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL_NAME`、`TEMPERATURE`、`MAX_TOKENS`、`RETRIEVER_BACKEND`、`FAQ_TOP_K`、`FAQ_MIN_SCORE`、`INTENT_USE_LLM`、`DEBUG`、`LOG_STORE_ENABLED`、`LOG_DB_PATH`、`ADMIN_API_KEY`、`RATE_LIMIT_ENABLED`、`RATE_LIMIT_REQUESTS`、`RATE_LIMIT_WINDOW`、`TRUST_FORWARDED_FOR`、`AUTH_SECRET`、`AUTH_TOKEN_TTL_SECONDS`、`ASR_ENABLED`、`ASR_MODEL_SIZE`。

模型走 OpenAI 兼容协议，换模型只改三个变量、代码零改动。本地 Ollama 把 base URL 指向 `http://localhost:11434/v1`；云端可选 DeepSeek、通义千问、智谱 GLM、月之暗面等。没有配 Key 也能启动，`DEBUG=true` 时模型调用失败会把错误显示在对话里，便于先跑通链路。

检索后端可插拔：`tfidf` 是默认值，纯 Python 字符 n-gram 实现、零依赖；`embedding` 走 sentence-transformers 加 FAISS，语义检索效果更好但要装重依赖；`auto` 优先语义、依赖缺失时自动回退 TF-IDF，不会因为少装包而启动失败。

## 测试与校验

后端 298 个用例全部离线可跑，用假客户端替换大模型、每个用例独立临时 SQLite，因此不需要 API Key、不产生网络请求与费用。

```bash
cd ecommerce-ai-customer-service
.venv/Scripts/python.exe -m pytest          # 298 用例
.venv/Scripts/python.exe -m ruff check      # 代码检查
```

```bash
cd apps/web
npm run build                               # vue-tsc -b && vite build
```

根目录 `npm test` 会串起前端测试与后端 pytest。pytest 配置在 `pytest.ini`，`asyncio-mode=auto`、`testpaths=tests`。

## 前端约定

页面路由共 7 条：`/`、`/products`、`/products/:id`、`/cart`、`/login`、`/account`、通配 404。商品数据启动时从 `/api/products` 拉取，请求失败静默降级到本地 `src/data/products.ts`，保证后端未启动时前端仍可浏览。

i18n 支持中英切换（`src/i18n/zh-CN.ts` 与 `en-US.ts`，切换器为 `LocaleSwitcher.vue`），但客服回复语言以后端为准。购物车状态存 `localStorage` 的 `nora:cart:v1`。

设计语言是 Apple-informed mono-chrome 极简风，色板与间距定义在 `src/style.css` 与 `tailwind.config.ts`：主色 Ink `#0A0A0A`、正文 `#1D1D1F`、次要文字 `#6E6E73`，表面 `#FFFFFF`、浅底 `#F5F5F7`、描边 `#E5E5E7`，强调蓝 `#0071E3`，语义色 `#FF3B30` 与 `#34C759`。字体 Inter 加 JetBrains Mono（SKU 用）。圆角 4/8/16/pill，CTA 一律 pill。禁用阴影，用 0.5px 描边代替。容器最大宽 1240px。

代码风格：组件 PascalCase、函数 camelCase、文件名 kebab-case；路径别名 `@/*` 指向 `src/*`；注释控制在三行以内；TypeScript strict 但不为严格而过度类型化。

## 已知坑

`--reload` 必须在前台终端里跑。以后台任务方式启动会被进程组回收，退出码 `3221225786`（`STATUS_CONTROL_C_EXIT`），看起来像崩溃，实际是宿主杀掉了进程组。

判断热重载是否生效不能看进程 ID。reloader 与 worker 的 PID 在 `--reload` 下保持不变，只有每轮重载派生的工作子进程 PID 会轮换。可靠的验证方式是改动一个不被 `.env` 覆盖的返回值（例如根路径字符串或某个接口响应），再看请求结果是否变化。

Python 虚拟环境在 `ecommerce-ai-customer-service/.venv/`，不在 `node_modules` 里，调用时要用 `.venv/Scripts/python.exe`。当前环境为 Python 3.13.14、uvicorn 0.52.4、watchfiles 1.2.0。

陈旧的 `__pycache__` 字节码缓存曾导致 `/auth/*` 路由返回 404，删除对应 `__pycache__` 目录并重启即可恢复。

ASR 在 Windows 加国内网络下需要设置 `HF_ENDPOINT=https://hf-mirror.com`、`HF_HUB_DISABLE_XET=1`、`HF_HUB_DISABLE_SYMLINKS=1`（ctranslate2 4.x 的兼容要求），用 `npm run -F @nora/api dev:asr` 会自动带上。模型缓存放在 `data/whisper-cache`，不污染用户主目录。默认 Alpine 镜像不含 ASR，`/chat/audio` 会返回 503，需要换 `Dockerfile.slim` 加 `--build-arg WITH_ASR=1`。

`DEBUG=true` 时 FastAPI 会在 500 响应里回显 traceback，生产环境必须设 `DEBUG=false`，否则内部堆栈会泄露给客户端。

限流默认不信任 `X-Forwarded-For`，因为该头可被伪造绕过限流，只有部署在可信反向代理之后才能设 `TRUST_FORWARDED_FOR=true`。

## 后续方向

支付尚未接入。多实例部署需要把内存里的会话历史、槽位、知识库索引换成 Redis 与向量库。token 目前是无状态的，登出仅前端丢弃，要做真正的失效需要把 `jti` 写入 Redis 黑名单。前端可补商品分页、筛选与详情 SSR。知识库只有 20 条 FAQ，同义改写场景下 TF-IDF 不如语义检索，可切 `embedding` 后端。订单与 FAQ 链路当前仍以 dict 传递，商品已收敛为 Pydantic 模型（`app/models/product.py`），其余可按需继续收敛。
