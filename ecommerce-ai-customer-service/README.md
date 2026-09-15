# 电商智能客服 · Ecommerce AI Customer Service

一个基于 **FastAPI + 大模型** 的电商智能客服系统，实现了「**意图识别 → 业务数据查询 → 知识库 RAG 检索 → 大模型生成 → 转人工兜底**」的完整对话链路，并自带一个可直接使用的网页聊天界面。

前端纯 HTML/CSS/JS，无需构建；后端接任意 **OpenAI 兼容** 接口（云端 API 或本地 Ollama 均可）。开箱即跑，无需数据库、无需联网下载模型；支持会话日志落库（SQLite）、管理接口、Docker 多阶段部署（默认 Alpine 镜像 ~175MB）、限流、**SSE 流式响应**、**PII 自动脱敏**、**LLM 重试+熔断**、**Prompt 注入防护**、**Markdown 渲染**、**FAQ 热更新**、**会话导出**、**用户反馈按钮**、**FAQ 检索缓存**、**多轮上下文压缩**、**🎙️ 离线 ASR**、**CI 流水线** 与 **268 个单元测试**。

---

## 目录

- [项目介绍](#项目介绍)
- [功能列表](#功能列表)
- [技术栈](#技术栈)
- [快速启动](#快速启动)
  - [1. 安装依赖](#1-安装依赖)
  - [2. 配置 .env](#2-配置-env)
  - [3. 启动服务](#3-启动服务)
  - [4. 打开聊天界面](#4-打开聊天界面)
- [Docker 部署](#docker-部署)
- [会话日志与管理接口](#会话日志与管理接口)
- [错误处理与限流](#错误处理与限流)
- [测试](#测试)
- [如何切换模型](#如何切换模型)
- [核心流程](#核心流程)
- [接口一览](#接口一览)
- [目录结构](#目录结构)
- [简历可写亮点](#简历可写亮点)
- [已知限制](#已知限制)

---

## 项目介绍

客服是电商场景中最重复、最耗人力的环节：查订单、问物流、问退换货政策、问优惠券规则……其中大部分是**可被自动化**的。

本项目用一套轻量、可插拔的架构解决这个问题：

- **能查真数据**：从用户消息里抽取订单号，直接查 `orders.json` 的订单与物流，交给大模型**基于真实数据**组织成自然语言回复——而不是让模型瞎编。
- **能答政策题**：对 FAQ 建检索索引，命中后作为上下文注入 Prompt（RAG），答案有据可依。
- **知道该找谁**：先做意图分类，识别到「转人工」或模型表示不确定时，走人工兜底。
- **不需要数据库、不需要 GPU**：默认检索后端是纯 Python 实现的 TF-IDF，零额外依赖；也可以一键切换到向量语义检索。

---

## 功能列表

### 对话能力

- ✅ **多轮对话**：以 `session_id` 维护会话历史，单会话默认保留最近 20 条；超出按 LRU 淘汰旧会话
- ✅ **意图识别**：7 类意图 —— 查询订单 / 查询物流 / 退换货 / 商品咨询 / 优惠活动 / 转人工 / 其他
  - 规则关键词优先（零成本、可离线），未命中再调大模型兜底分类
- ✅ **知识库 RAG**：对 20 条 FAQ 建索引，检索 top-k 作为上下文注入 Prompt
- ✅ **订单 / 物流查询**：从消息抽取订单号 → 查真实模拟数据 → 注入 Prompt
  - 支持**精确 / 后缀 / 包含**三级匹配（`202609030002`、`0002`、`123456` 都能查到）
  - 自动排除手机号，避免误识别
- ✅ **会话槽位（slot）**：记住已查到的订单号，追问「那物流到哪了」时自动复用
- ✅ **主动澄清**：用户没给订单号时，Prompt 会指示模型主动索要
- ✅ **转人工兜底**：命中「转人工」意图直接返回提示（不消耗 token）；模型回答含「不清楚 / 信息不足」等措辞时自动追加转人工提示
- ✅ **SSE 流式响应**（`POST /chat/stream`）：token-by-token 推送给前端，体验接近 ChatGPT
- ✅ **Prompt 注入防护**：检测「忽略上述指令」「you are now」「system:」「&lt;/system&gt;」等典型越权模式 → 自动转人工并告警
- ✅ **LLM 弹性**：`achat` 自带指数退避重试（默认 3 次）+ 熔断器（连续 5 次失败 → 30s 冷却 → 半开探测）
- ✅ **PII 自动脱敏**：手机号、邮箱、身份证、银行卡、订单号、IPv4 全部按规则脱敏（结构化日志 + 持久化都生效）
- ✅ **会话恢复**：服务重启后自动从 SQLite 回填最近活跃的会话历史到内存中

### 工程能力

- ✅ **配置全部走环境变量**（pydantic-settings），无硬编码密钥
- ✅ **可插拔检索后端**：`tfidf`（默认，零依赖）/ `embedding`（sentence-transformers + FAISS）/ `auto`
- ✅ **提示模型可配置**：Base URL、模型名、温度、max_tokens、超时
- ✅ **调试友好**：`DEBUG=true` 时模型调用失败会把错误回显到对话中，没有 API Key 也能联调
- ✅ **自带网页聊天界面**：多轮对话、清空对话、意图与引用标签、快捷提问、连接状态、深浅色自适应、移动端适配
- ✅ **Markdown 渲染**：前端 `marked.js` 把大模型回复渲染为带表格 / 列表 / 代码块 / 链接的富文本；自带 XSS 兜底防护
- ✅ **FAQ 热更新**：`POST /knowledge/reload` 无需重启服务即可重建索引（外部脚本监听文件后调用）
- ✅ **会话导出**：`GET /admin/sessions/{id}/export?format=md|json` 把单会话导出为 Markdown（含元信息）或 JSON
- ✅ **会话日志落库**：每轮对话持久化到 SQLite（意图 / 引用来源 / 订单 / 是否转人工），可复盘、可统计
- ✅ **管理接口**：分页查看会话列表、会话详情、关键词搜索、统计、删除；支持 `X-Admin-Key` 鉴权（多 Key 灰度轮换）
- ✅ **SQLite 性能调优**：WAL + `synchronous=NORMAL` + 64MB 页缓存 + 256MB mmap，写性能 2-3× 提升
- ✅ **统一错误处理**：所有错误响应结构一致（`{"error": {"code", "message", "detail"}}`），500 不泄露内部堆栈
- ✅ **限流**：零依赖滑动窗口限流中间件（按 IP），正则精确匹配豁免路径，超限返回 429 + `Retry-After`
- ✅ **优雅退出**：SIGTERM/SIGINT 信号触发 lifespan 关闭，LogStore 后台 worker 在 5s 窗口内排空队列
- ✅ **Docker 多阶段构建**：
  - `Dockerfile`（默认，alpine 3.13 + 多阶段）：**实测 175 MB**，目标 < 200MB ✅
  - `Dockerfile.slim`（debian-slim + faster-whisper）：约 1.48GB，含完整 ASR 能力
  - 通过 `--build-arg WITH_ASR=1` 启用 ASR；通过 `docker compose --profile asr` / `--profile asr-preloaded` 切换
  - HEALHCHECK + curl + tini init + 非 root 运行；模型权重不进镜像（运行时挂载）
- ✅ **CI 流水线**：GitHub Actions（ubuntu + windows × Python 3.12/3.13）跑 lint + 268 个测试 + Docker 镜像大小校验
- ✅ **268 个单元测试**：pytest 全离线可跑（假客户端替代大模型，临时 SQLite，无需 API Key）

### 体验增强（P2）

- ✅ **👍 / 👎 反馈按钮**：每条 bot 气泡下方加反馈按钮，调用 `POST /chat/{session_id}/feedback` 写入 SQLite 的 `feedback` 表；管理端可按会话或全局统计正负反馈比例，用于后续模型评估与 bad-case 复盘
- ✅ **FAQ 检索缓存**：`query + top_k` 为 key 的 5 分钟 TTL 缓存，`hits/misses` 统计可读；reload 自动清空；`FAQ_CACHE_TTL=0` 可关闭
- ✅ **多轮上下文压缩**：对话超过阈值（默认 10 轮）时调 LLM 把早期历史压缩成 200 字摘要，每会话最多 1 次；摘要失败时主流程不受影响

### 🎙️ 离线 ASR（P3）

- ✅ **faster-whisper 离线转写**：`POST /chat/audio` 上传 webm/wav/mp3 → 调本地 `WhisperModel` 转写为文本
- 🆕 **WebSocket 流式 ASR**：`WS /asr/stream` 边录边识别（协议：首帧 `{"event":"start"}` → 二进制音频帧 → `{"event":"stop"}` → 服务端节流跑 faster-whisper 推 `partial` → 停止跑 `final`）。前端把 partial 文本实时回显到识别预览气泡和输入框
- ✅ **懒加载模型单例**：第一次请求才下载 + 加载模型权重（small 约 460MB，base 约 140MB），避免启动卡住
- ✅ **前端 🎙️ 录音按钮（流式）**：`MediaRecorder` 把音频 chunk 通过 WebSocket 推到 `/asr/stream`，识别过程实时可视化
- ✅ **可选 Docker 镜像**：`Dockerfile`（alpine，默认 175MB，不含 ASR）/ `Dockerfile.slim`（debian-slim + faster-whisper，约 1.5GB）通过 compose profile 切换
  - `asr` profile：运行时按需下载 + named volume 缓存
  - 🆕 `asr-preloaded` profile：**不挂** volume，模型 baked 在镜像里（避免 volume 遮罩 baked 层）
- 🆕 **Release workflow**：`.github/workflows/release.yml` 监听 `release:published`，自动构建多平台 `ecs:asr-base` / `ecs:asr-small` 镜像（带 PRELOAD_MODEL=1）推 GHCR
- 🆕 **E2E 验证脚本**：`scripts/verify-asr-e2e.sh` 用户本机一键跑通"预烤 → 真实转写"
- ✅ **自动接口文档**：FastAPI 生成的 Swagger UI

---

## 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 后端框架 | **FastAPI** | 异步、自动生成 OpenAPI 文档 |
| ASGI 服务器 | **Uvicorn** | 支持 `--reload` 热重载 |
| 配置管理 | **pydantic-settings** | 从环境变量 / `.env` 读取并校验 |
| 数据模型 | **Pydantic v2** | 请求 / 响应模型校验 |
| 大模型 | **OpenAI 兼容接口**（openai SDK） | 官方 / Ollama / DeepSeek / 通义千问 等 |
| 知识库检索 | **中文 TF-IDF**（默认，纯 Python） | 字符 n-gram 切分，零依赖 |
| 知识库检索（可选） | **sentence-transformers + FAISS** | 语义检索，需额外安装 |
| 会话日志 | **SQLite**（标准库 sqlite3） | 零依赖、WAL 模式，可整体关闭 |
| 业务数据 | **JSON 文件**（faq.json / orders.json） | 无需数据库 |
| 前端 | **原生 HTML / CSS / JavaScript** | 无构建步骤，`fetch` 调后端 |
| 测试 | **pytest** | 268 个用例，全离线 |
| 部署 | **Docker / docker compose** | 非 root、健康检查、数据卷持久化 |

**依赖一览**（`requirements.txt`）：`fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`、`python-dotenv`、`httpx`、`openai`。可选：`sentence-transformers`、`faiss-cpu`。开发依赖见 `requirements-dev.txt`（`pytest`）。

---

## 快速启动

### 1. 安装依赖

要求 Python ≥ 3.10（开发环境为 3.13）。

```bash
cd ecommerce-ai-customer-service

# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置 .env

复制模板并按需修改：

```bash
cp .env.example .env     # Windows: copy .env.example .env
```

`.env` 关键配置：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 大模型 API Key（用 Ollama 时随便填，如 `ollama`） | 空 |
| `OPENAI_BASE_URL` | 兼容 OpenAI 的接口地址 | `https://api.openai.com/v1` |
| `MODEL_NAME` | 模型名 | `gpt-4o-mini` |
| `TEMPERATURE` / `MAX_TOKENS` | 生成参数 | `0.7` / `1024` |
| `RETRIEVER_BACKEND` | 检索后端：`tfidf` / `embedding` / `auto` | `tfidf` |
| `FAQ_TOP_K` / `FAQ_MIN_SCORE` | 检索条数 / 命中阈值 | `3` / `0.15` |
| `INTENT_USE_LLM` | 规则未命中时是否用大模型兜底分类 | `true` |
| `DEBUG` | 调试模式（模型报错回显到对话） | `true` |
| `LOG_STORE_ENABLED` / `LOG_DB_PATH` | 是否落库会话日志 / SQLite 路径 | `true` / `data/app.db` |
| `ADMIN_API_KEY` | 管理接口密钥（留空则不校验） | 空 |
| `RATE_LIMIT_ENABLED` | 是否开启限流 | `true` |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW` | 窗口内请求数 / 窗口秒数 | `60` / `60` |
| `TRUST_FORWARDED_FOR` | 是否信任 `X-Forwarded-For`（置于可信代理后才开） | `false` |

> 想先跑起来看效果、又还没有 Key？**直接跳过这一步也能启动**（`DEBUG=true` 下模型调用失败会把错误信息显示在对话里），先把界面和链路跑通，再回来填 Key。

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

或：

```bash
python -m app.main
```

> **端口提示**：上面的裸跑 / Docker 方式默认监听 **8000**。
> 若通过 monorepo 根目录的 `npm run dev:api` 启动，会固定使用 **8001**（避开本机被占用的 8000），
> 此时 Vue 门店（5173）已通过 Vite 代理把 `/api/*`、`/asr/*` 转发到 8001。
>
> **Vue 门店客服入口**：在 monorepo 里 `npm run dev` 后访问 http://127.0.0.1:5173 ，
> 页面右下角即有 AI 客服浮动窗（流式对话 + 语音），本目录下的 `frontend/` 仅为旧版独立测试页。

启动后：

| 地址 | 说明 |
| --- | --- |
| http://127.0.0.1:8000/ui | **网页聊天界面** |
| http://127.0.0.1:8000/ | 返回 `Hello, AI Customer Service` |
| http://127.0.0.1:8000/health | 健康检查 |
| http://127.0.0.1:8000/docs | Swagger 接口文档 |

### 4. 打开聊天界面

**方式一（推荐）**：浏览器访问 <http://127.0.0.1:8000/ui>，由后端直接托管前端，无需任何额外配置。

**方式二**：直接双击打开 `frontend/index.html`（`file://` 协议）。此时跨域来源为 `null`，后端默认已放行；若端口不是 8000，点击界面右上角 ⚙️ 填写后端地址即可。

试试这些输入：

```
查一下我的订单 123456        → 查到订单 202612345678（运输中）及物流轨迹
那物流到哪了                 → 自动复用上一轮的订单号
退款多久能到账？              → 命中 FAQ 知识库
我要转人工                   → 直接返回转人工提示
```

---

## Docker 部署

无需本地 Python 环境，一条命令起服务。

### 方式一：docker compose（推荐）

```bash
# 可选：先准备好 .env（compose 会自动读取其中的变量）
cp .env.example .env

docker compose up -d --build
docker compose logs -f
```

访问 <http://127.0.0.1:8000/ui>。停止：

```bash
docker compose down
```

`data/` 目录已挂载到宿主机（`./data:/app/data`），因此：
- SQLite 会话日志会持久化，容器重建不丢数据；
- 可以直接修改宿主机的 `data/faq.json`、`data/orders.json` 再重启容器。

### 🆕 方式一.B：ASR 离线转写（流式）

```bash
# A. 运行时下载 + named volume 缓存（首次 ~150MB 下载）
PRELOAD_MODEL=0 docker compose --profile asr up -d --build
# → http://127.0.0.1:8001/ui

# B. 预烤模型到镜像（构建慢，但首请求 0 延迟；适合 release / 离线）
PRELOAD_MODEL=1 docker compose --profile asr-preloaded up -d --build
# → http://127.0.0.1:8002/ui
```

> ⚠️ 两种 profile 的区别仅在于"模型存在哪"：**A** 在 named volume（可被 cache 重用），**B** 在镜像层（不可变 + 可复现）。**不要**在 `asr-preloaded` 上挂 `asr-cache` volume，会遮罩 baked 模型。

**E2E 自检脚本**（推荐先跑一遍）：

```bash
bash scripts/verify-asr-e2e.sh   # base 模型，约 1-2 分钟
ASR_MODEL_SIZE=small bash scripts/verify-asr-e2e.sh   # small 模型
```

### 方式二：docker run

```bash
docker build -t ecommerce-ai-customer-service:latest .

docker run -d --name ecommerce-ai-cs \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  ecommerce-ai-customer-service:latest
```

### 镜像做了什么

- 基于 `python:3.13-slim`，先复制 `requirements.txt` 装依赖，**充分利用层缓存**
- **非 root 用户**（`appuser`）运行，降低容器逃逸风险
- 内置 **HEALTHCHECK**（轮询 `/health`）
- `.dockerignore` 排除 `.venv`、`.env`、`tests`、本地 `*.db` 等，**密钥不进镜像**

### 连本地 Ollama

容器内的 `localhost` 不是宿主机。若 Ollama 跑在宿主机上：

```bash
# 让 Ollama 监听所有网卡（macOS/Linux 默认已监听 0.0.0.0）
OLLAMA_HOST=0.0.0.0 ollama serve
```

```yaml
# docker-compose.yml 里把 BASE_URL 指向宿主机
environment:
  OPENAI_BASE_URL: http://host.docker.internal:11434/v1
  OPENAI_API_KEY: ollama
  MODEL_NAME: qwen2.5:7b
```

---

## 会话日志与管理接口

每轮对话都会写入本地 **SQLite**（`data/app.db`），用于复盘与统计。
可用 `LOG_STORE_ENABLED=false` 整体关闭（关闭后管理接口返回空数据）。

**表结构**（自动建表）：

| 表 | 说明 |
| --- | --- |
| `sessions` | 会话汇总：创建/更新时间、消息数、最近意图、转人工次数 |
| `messages` | 每条消息：角色、内容、意图、引用来源(JSON)、订单号、是否命中知识库、是否转人工、时间 |

**管理接口**：

```bash
# 会话列表（分页）
curl "http://127.0.0.1:8000/admin/sessions?limit=20&offset=0"

# 某会话的完整对话
curl "http://127.0.0.1:8000/admin/sessions/<session_id>"

# 统计：会话数、消息数、转人工会话数、意图分布
curl "http://127.0.0.1:8000/admin/stats"

# 关键词搜索消息
curl "http://127.0.0.1:8000/admin/search?q=退款"

# 删除某会话日志
curl -X DELETE "http://127.0.0.1:8000/admin/sessions/<session_id>"
```

**鉴权**：设置 `ADMIN_API_KEY` 后，所有 `/admin/*` 请求必须携带请求头 `X-Admin-Key`，否则返回 401：

```bash
curl -H "X-Admin-Key: your-secret" "http://127.0.0.1:8000/admin/stats"
```

> 留空密钥 = 不校验，**仅适合本地开发**。生产环境务必设置。

---

## 错误处理与限流

### 统一错误响应

所有错误（含 404 / 422 / 429 / 500）结构一致，客户端只需一套解析逻辑：

```json
{
  "error": {
    "code": "validation_error",
    "message": "请求参数校验失败",
    "detail": [ { "loc": ["body", "message"], "msg": "String should have at least 1 character", "type": "string_too_short" } ]
  }
}
```

| 场景 | status | `code` |
| --- | --- | --- |
| 资源不存在 | 404 | `http_404` |
| 方法不允许 | 405 | `http_405` |
| 管理接口鉴权失败 | 401 | `http_401` |
| 参数校验失败 | 422 | `validation_error` |
| 触发限流 | 429 | `rate_limited` |
| 未捕获异常 | 500 | `internal_error` |

> 500 响应**不包含**内部堆栈或异常原文，只记录到服务端日志，避免信息泄露。
> 注意：`DEBUG=true` 时 FastAPI 会返回 traceback 以方便定位，**生产环境请设 `DEBUG=false`**。

### 限流

基于「滑动窗口 + 时间戳队列」的内存限流中间件，零额外依赖：

- 默认 **60 次 / 60 秒 / IP**，超限返回 `429` + `Retry-After` 头
- 免限流路径：`/health`、`/docs`、`/redoc`、`/openapi.json`、`/ui` 等（可配置）
- 中间件顺序：**限流在内层、CORS 在外层**，这样 429 也会带上跨域头，前端才能读到状态码
- 默认**不信任** `X-Forwarded-For`（该头可被伪造用于绕过限流）；置于可信反向代理之后再设 `TRUST_FORWARDED_FOR=true`

---

## 测试

268 个单元测试，**全程离线**：用假客户端替换大模型、每个用例独立临时 SQLite，因此不需要 API Key、不产生网络请求与费用。

```bash
pip install -r requirements-dev.txt   # 安装 pytest
pytest                                # 或 python -m pytest
```

覆盖率分布：

| 测试文件 | 用例数 | 覆盖内容 |
| --- | --- | --- |
| `test_order_service.py` | 26 | 订单号提取、三级匹配、格式化、边界（手机号、无号、查不到） |
| `test_intent_service.py` | 25 | 7 类意图规则、优先级消歧、大模型兜底、结果解析 |
| `test_chat_api.py` | 18 | `/chat` 端到端：多轮、槽位复用、RAG 注入、转人工、落库 |
| `test_knowledge_base.py` | 15 | 分词、TF-IDF 检索、阈值过滤、上下文拼装 |
| `test_admin_api.py` | 14 | 会话列表/详情/搜索/统计/删除 + 鉴权 |
| `test_dialogue_manager.py` | 14 | 历史增删改查、裁剪、LRU 淘汰、槽位 |
| `test_log_store.py` | 12 | SQLite 读写、JSON 往返、统计、开关降级 |
| `test_rate_limit.py` | 8 | 窗口限流、429/Retry-After、豁免路径、客户端识别 |
| `test_knowledge_api.py` | 7 | `/knowledge/*` 检索接口 |
| `test_orders_api.py` | 7 | `/orders/*` 查询接口 |
| `test_errors.py` | 6 | 统一错误结构、校验明细、500 不泄露堆栈 |

---

## 如何切换模型

所有模型调用都走 **OpenAI 兼容协议**，只需改 `.env` 里的三个变量，代码零改动。

### 方案 A：本地 Ollama（免费、数据不出本机）

```bash
# 1. 安装 Ollama 并拉取模型
ollama pull qwen2.5:7b
```

```env
# 2. .env
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama          # Ollama 不校验，随便填
MODEL_NAME=qwen2.5:7b
```

### 方案 B：云端 API

| 服务 | `OPENAI_BASE_URL` | `MODEL_NAME` 示例 |
| --- | --- | --- |
| OpenAI 官方 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问（DashScope） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 月之暗面 Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

示例（DeepSeek）：

```env
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
MODEL_NAME=deepseek-chat
```

> 改完 `.env` 后重启服务即可生效。

### 顺带一提：切换检索后端

```env
# 语义检索（需先 pip install sentence-transformers faiss-cpu）
RETRIEVER_BACKEND=embedding
EMBEDDING_MODEL=shibing624/text2vec-base-chinese
```

或设 `RETRIEVER_BACKEND=auto`：优先用语义检索，依赖缺失时自动回退 TF-IDF，不会因为少装包而启动失败。

---

## 核心流程

主流程在 `app/services/chat_service.py`：

```
用户消息
  │
  ├─ 1. 意图识别        intent_service    规则关键词优先 → 未命中调大模型分类
  │
  ├─ 2. 业务数据查询     order_service     仅订单类意图
  │        订单号：消息提取 → 回退会话槽位
  │        匹配：精确 → 后缀 → 包含
  │        命中则写入槽位，供后续追问复用
  │
  ├─ 3. 知识库检索       knowledge_base    检索 top-k FAQ（低于阈值视为未命中）
  │
  ├─ 4. 组装 Prompt     system = 角色 + 规则 + 意图 + 知识库上下文 + 业务数据
  │        未给订单号时追加【本轮提示】→ 模型主动索要
  │
  ├─ 5. 大模型生成       llm_service       异步调用 OpenAI 兼容接口
  │
  ├─ 6. 转人工判定
  │        · 意图 = 转人工 → 直接返回（不调用大模型）
  │        · 回复含不确定措辞 → 追加转人工提示
  │
  └─ 7. 持久化
           · dialogue_manager  写入内存会话历史与槽位
           · log_store         写入 SQLite 会话日志（可复盘 / 统计）
```

---

## Docker 构建选项

项目提供 **两个 Dockerfile** + 4 个 build arg，覆盖「不需 ASR」到「完整 ASR 离线」的场景。

### 文件选择

| Dockerfile | 基础镜像 | ASR | 目标大小 | 适用 |
|---|---|---|---|---|
| `Dockerfile`（默认） | `python:3.13-alpine` | ❌ | **~175MB** | 90% 生产场景（无语音） |
| `Dockerfile.slim` | `python:3.13-slim` | ✅（可选） | ~290MB / ~1.5GB | 需要 ASR |

### Build Args

| 参数 | 作用 | 默认 |
|---|---|---|
| `WITH_ASR` | 是否安装 faster-whisper | `0`（slim）/ N/A（alpine） |
| `PRELOAD_MODEL` | 是否在 build 阶段把 ASR 模型权重烤进镜像 | `0` |
| `ASR_MODEL_SIZE` | 预烤的模型大小（`tiny` / `base` / `small` / `medium`） | `small` |

### 用法示例

```bash
# 1) 默认 Alpine 镜像（最轻，175MB，无 ASR）
docker build -t ecs:app .

# 2) ASR 镜像：装好 faster-whisper 但运行时按需下载模型
docker build -f Dockerfile.slim --build-arg WITH_ASR=1 -t ecs:asr .

# 3) ASR 镜像：预烤 base 模型（~140MB 增量），首请求 0 延迟
docker build -f Dockerfile.slim --build-arg WITH_ASR=1 --build-arg PRELOAD_MODEL=1 -t ecs:asr-base .

# 4) ASR 镜像：预烤 small 模型（~460MB 增量），识别更准
docker build -f Dockerfile.slim --build-arg WITH_ASR=1 --build-arg PRELOAD_MODEL=1 --build-arg ASR_MODEL_SIZE=small -t ecs:asr-small .
```

### 预下载失败的处理

如果 `PRELOAD_MODEL=1` 时 builder 阶段**网络不可达**（如 CI 沙箱 / 公司内网），
build **不会失败** — entrypoint 会打印 `preloaded: <size>`，运行时 `/chat/audio` 会返回：

```json
{"error":{"code":"http_503","message":"... 'asr_model_download_failed', 'message': '无法下载 faster-whisper 模型 small：网络不可达。请设置 PRELOAD_MODEL=1 预烤进镜像，或检查网络/HF_ENDPOINT' ..."}}
```

前端可按 `code` 提示用户检查网络或切到预烤版本。

---

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/chat` | 发送消息，返回回复 + 意图 + 引用来源 + 订单信息 |
| POST | `/chat/stream` | **SSE 流式对话**：首包 meta → 多次 delta → 末包 done |
| GET | `/chat/{session_id}` | 查看会话历史 |
| DELETE | `/chat/{session_id}` | 清空会话历史 |
| POST | `/knowledge/reload` | **强制重建 FAQ 索引**（修改 faq.json 后调用） |
| GET | `/knowledge/search?q=&top_k=` | 检索知识库（调试用） |
| GET | `/knowledge/stats` | 知识库规模与检索后端信息 |
| GET | `/orders/{order_no}` | 按订单号查询（支持后 4-6 位） |
| GET | `/orders?user_id=u1001` | 查询某用户全部订单 |
| GET | `/admin/sessions` | 会话日志列表（分页） |
| GET | `/admin/sessions/{session_id}` | 会话日志详情 |
| GET | `/admin/sessions/{session_id}/export?format=md\|json` | **导出会话**（Markdown 给工单 / JSON 给数据团队） |
| GET | `/admin/search?q=` | 按关键词搜索消息 |
| GET | `/admin/stats` | 会话统计与意图分布 |
| POST | `/admin/feedback` | 写入反馈（管理端代提交） |
| GET | `/admin/feedback/stats` | 正/负反馈全局统计 |
| GET | `/admin/sessions/{session_id}/feedback` | 取某会话的全部反馈 |
| DELETE | `/admin/sessions/{session_id}` | 删除会话日志 |
| POST | `/chat/{session_id}/feedback` | **前端提交 👍/👎**（无需鉴权） |
| GET | `/health` | 基础健康检查 |
| GET | `/health/deep` | 深度健康检查（含 SQLite 可写 + LLM 配置状态 + ASR 状态） |
| POST | `/chat/audio` | **上传音频并转写**（multipart；alpine 镜像返回 503，slim-ASR 镜像可用） |
| GET | `/asr/status` | ASR 状态（enabled / loaded / 模型大小 / 失败次数） |
| WS  | `/asr/stream` | **🆕 流式 ASR**（MediaRecorder → 边录边识别 → 文本实时回流；详见 `app/services/asr_stream.py`） |

> `/admin/*` 若配置了 `ADMIN_API_KEY`，需携带请求头 `X-Admin-Key`。

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "查一下我的订单 123456", "session_id": "demo-1"}'
```

响应：

```json
{
  "reply": "您的订单 202612345678 正在运输中……",
  "session_id": "demo-1",
  "intent": { "intent": "query_order", "label": "查询订单", "confidence": 0.6, "method": "rule" },
  "sources": [ { "id": "faq_001", "category": "订单", "question": "如何查询我的订单？", "score": 0.6871 } ],
  "transferred": false,
  "grounded": true,
  "order_no": "202612345678",
  "order_found": true
}
```

SSE 流式调用：

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": "demo-1"}'
```

事件序列：

```
data: {"event": "meta",  "data": {"session_id": "...", "intent": {...}, "sources": [...]}}
data: {"event": "delta", "data": {"text": "你"}}
data: {"event": "delta", "data": {"text": "好，"}}
data: {"event": "delta", "data": {"text": "请问需要什么帮助？"}}
data: {"event": "done",  "data": {"transferred": false, "grounded": false}}
```

---

## 目录结构

```
ecommerce-ai-customer-service/
├── app/
│   ├── main.py                   # FastAPI 入口（注册路由 + 托管前端）
│   ├── config.py                 # 配置（pydantic-settings 从环境变量读取）
│   ├── api/                      # 路由层（只做协议，不写业务）
│   │   ├── chat.py               #   POST /chat
│   │   ├── knowledge.py          #   GET  /knowledge/*
│   │   └── orders.py             #   GET  /orders/*
│   ├── services/                 # 业务层
│   │   ├── chat_service.py       #   对话编排主流程
│   │   ├── intent_service.py     #   意图识别（规则 + 大模型）
│   │   ├── order_service.py      #   订单号提取 / 订单查询 / 物流格式化
│   │   ├── knowledge_base.py     #   FAQ 知识库索引与检索
│   │   ├── retriever.py          #   检索后端（TF-IDF / Embedding）
│   │   ├── llm_service.py        #   大模型调用（OpenAI 兼容）
│   │   └── dialogue_manager.py   #   会话历史 + 槽位管理
│   ├── models/                   # 数据模型（预留）
│   └── utils/
│       └── data_loader.py        #   JSON 数据加载（带缓存）
├── data/
│   ├── faq.json                  # 20 条 FAQ（9 大类）
│   └── orders.json               # 8 个订单（含商品与物流轨迹）
├── frontend/                     # 网页聊天界面（零构建）
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── requirements.txt
├── .env.example
└── README.md
```

---

## 简历可写亮点

如果要把这个项目写进简历，可以从「**问题 → 方案 → 量化结果**」的角度切入：

**项目一句话**：基于 FastAPI 的电商智能客服系统，实现意图识别、业务数据查询与知识库 RAG 的完整对话链路，支持任意 OpenAI 兼容模型（云端 / 本地 Ollama），并具备生产级可观测性与弹性。

**可突出的技术点**：

1. **RAG 检索增强**：设计可插拔检索层（抽象出统一 `search` 接口），实现**零依赖中文 TF-IDF** 与 **sentence-transformers + FAISS 语义检索**双后端，通过配置切换并支持依赖缺失时自动降级——避免"绑死重型依赖"导致部署失败。
2. **意图识别降本设计**：采用「**规则优先 + 大模型兜底**」两级策略，高频意图走关键词规则零成本命中，仅长尾走模型分类，显著减少 LLM 调用次数与响应延迟。
3. **RAG 注入业务数据**：从自然语言中抽取订单号（正则 + 手机号排除 + 三级容错匹配），把**结构化订单/物流数据**注入 Prompt，让模型基于真实数据作答，有效抑制幻觉（避免编造订单号、金额、时间）。
4. **对话状态管理**：实现会话级**历史管理 + 槽位（slot）机制**，支持多轮追问时自动复用上下文中的订单号；内含历史裁剪与 LRU 会话淘汰，控制内存增长；**服务重启时从 SQLite 回填最近活跃会话**。
5. **生产级 LLM 弹性**：`achat` 自带**指数退避重试**（区分可恢复/不可恢复错误）+ **进程级熔断器**（closed → open → half_open 状态机），大模型短暂抖动不致雪崩；流式路径独立于熔断探测。
6. **SSE 流式响应**：基于 OpenAI `stream=True` 实现 token-by-token 输出，前端用 `fetch + ReadableStream` 手动解析 SSE，体感接近 ChatGPT；设置面板可一键关闭走非流式接口兜底。
7. **Prompt 注入防护**：检测「忽略上述指令」「you are now」「system:」「`</system>`」等典型越权模式 → 自动转人工并写入结构化告警日志；hardened system prompt 明确不可被用户消息覆盖的身份声明。
8. **PII 自动脱敏**：手机号、邮箱、身份证、银行卡、订单号、IPv4 全部按规则脱敏；统一在 JSON 结构化日志格式器 + LogStore 持久化前应用，避免敏感数据泄漏到日志聚合系统。
9. **转人工兜底策略**：意图命中「转人工」时跳过模型调用直接响应（省 token）；通过不确定措辞检测自动追加人工兜底提示，并针对订单流程做误判规避。
10. **工程化与可测试性**：分层架构（api / services / utils）职责清晰；配置全量环境变量化，无硬编码密钥；**268 个单元测试完全离线运行**（fake LLM client 拦截调用），无 API Key 也能完成端到端测试；接入 **GitHub Actions CI**（多 OS × 多 Python）自动跑 lint + 测试 + Docker 构建。
11. **零构建前端**：纯 HTML/CSS/JS 实现多轮对话、流式打字动画、意图与引用标签、会话持久化（localStorage）、深浅色自适应、PII 脱敏支持，并解决 `file://` 直开的跨域问题。

**可量化的表述参考**（按实际测得的数字填）：

- FAQ 知识库检索 **Top-1 命中率 100%**（20 条 FAQ，覆盖 9 大类意图场景）
- 高频意图（订单/物流/退换货/优惠等）由规则命中，**约 80% 请求无需调用大模型做意图分类**
- 「转人工」场景**单请求 0 次模型调用**
- 日志落盘走 `asyncio.Queue` 后台批写，**请求路径零阻塞**（批量 50 条 / 0.5s 触发）
- LLM 调用 3 次重试 + 熔断保护，**故障场景下请求不雪崩**
- 无数据库、无 GPU 依赖，**`pip install` 后即可启动**，冷启动约数百毫秒
- **268 个 pytest 测试离线可全部跑完**（零 API 成本；CI 缓存后约 1 分钟以内）
- **GitHub Actions CI** 多 OS × 多 Python 版本自动跑 lint + test + Docker 镜像大小校验
- **Docker Alpine 镜像实测 175MB**（默认 `Dockerfile`）；ASR 镜像 `Dockerfile.slim` + `--build-arg WITH_ASR=1` 约 1.48GB
- **faster-whisper 离线 ASR**：`/chat/audio` 上传音频 → 端侧 lazy load 小模型 → 转写回填输入框；首次请求 ~3-5s（模型下载），之后 <500ms
- **多 Dockerfile 策略**：Alpine 镜像作为默认（覆盖 90% 场景），Slim+ASR 镜像通过 profile 切换
- **ASR 模型可预烤进镜像**：`--build-arg PRELOAD_MODEL=1` 在 build 阶段预下载小模型到镜像内（~140MB-460MB），启动即可用，首请求零延迟
- **ASR 错误码细分**：`asr_model_download_failed`（网络不可达，503）vs `asr_model_load_failed`（模型损坏，503）vs `asr_transcribe_failed`（音频格式错误，422）；前端可按 code 分别提示用户
- **CI asr-e2e job**：`docker compose --profile asr` 跑 e2e：构建 → 启动 → `/asr/status` 结构校验 → `/chat/audio` 503 结构校验

---

## 已知限制

- **订单查询默认不强制身份校验**：`GET /orders/{order_no}` 已支持可选 `user_id` 归属校验（传入且归属不一致返回 403），但未接登录态时不传仍可查（演示用）。生产环境必须从登录态 / 令牌解析用户身份并**强制**校验，否则存在**越权查询**风险；对话链路中的订单查询同理。
- **数据在内存**：会话历史、槽位与知识库索引均在进程内存中；服务重启时会**从 SQLite 回填**，但极端情况（如长会话被 LRU 淘汰）仍有少量上下文丢失。多实例部署需替换为 Redis / 向量数据库。
- **知识库规模小**：20 条 FAQ 用于演示；TF-IDF 对同义改写（如"钱啥时候退我"）不如语义检索，需要时切 `embedding` 后端。
- **业务模型部分仍是 dict**：商品接口已收敛为 Pydantic 模型（`app/models/product.py`）；订单 / FAQ 等链路目前仍以 `dict` 传递，可按需继续收敛。
- **限流维度**：当前按客户端 IP 限流，未做按 `session_id` 或用户维度的精细化限流。

---

## 说明

- `.env` 已被 `.gitignore` 忽略，请勿提交密钥。
- `data/` 下均为模拟数据，仅供演示。
