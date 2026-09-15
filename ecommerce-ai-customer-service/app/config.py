"""应用配置模块。

使用 pydantic-settings 从环境变量 / .env 文件读取配置。
复制 .env.example 为 .env 并按需修改：

    cp .env.example .env

字段名与环境变量名大小写不敏感地一一对应，
例如 `openai_api_key` 对应环境变量 `OPENAI_API_KEY`。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/config.py -> 上溯一级）
BASE_DIR: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置项。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用基础 ----------
    app_name: str = "Ecommerce AI Customer Service"
    app_env: str = "development"
    debug: bool = False
    version: str = "0.7.0"

    # ---------- 服务监听 ----------
    host: str = "127.0.0.1"
    port: int = 8000

    # ---------- 日志 ----------
    # 留空 → 只输出到 stdout（容器友好）；填写路径 → 追加写文件
    log_file: str = ""
    # 是否在日志/持久化前做 PII 脱敏（默认开启）
    redact_pii: bool = True

    # ---------- CORS ----------
    # 逗号分隔的来源，例如: http://localhost:8000,http://127.0.0.1:8000
    # 生产环境只应配置实际受控的 HTTPS 前端域名；不要加入 ``null``。
    allowed_origins: str = (
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    # ---------- 数据 ----------
    data_dir: str = "data"

    # ---------- 会话日志（SQLite） ----------
    # 是否把会话与消息持久化到 SQLite
    log_store_enabled: bool = True
    # SQLite 文件路径（相对路径以项目根目录为基准）
    log_db_path: str = "data/app.db"
    # 后台 flush worker 批次大小（消息条数）
    log_store_batch_size: int = 50
    # 后台 flush worker 间隔（毫秒）
    log_store_flush_interval_ms: int = 500

    # ---------- 管理接口 ----------
    # 留空表示不校验（仅建议本地开发）；设置后需带 X-Admin-Key 请求头
    admin_api_key: str = ""
    # 多个 admin key（逗号分隔），用于灰度轮换；任一命中即可
    admin_api_keys: str = ""

    # ---------- 鉴权（HMAC-SHA256 自签 token）----------
    # 是否启用鉴权依赖；False 时订单接口也放行（仅本地/测试用）
    auth_enabled: bool = True
    # 签名密钥；空字符串时 fallback 到 tokens.py 内置演示常量（生产必填）
    auth_secret: str = ""
    # token 有效期（秒），默认 24h
    auth_token_ttl_seconds: int = 86400

    # ---------- 限流（内存滑动窗口，按客户端 IP） ----------
    rate_limit_enabled: bool = True
    # 每个窗口内允许的请求数
    rate_limit_requests: int = 60
    # 窗口长度（秒）
    rate_limit_window: int = 60
    # 登录接口使用更严格的独立额度，降低撞库和密码猜测风险。
    # 个人部署默认关闭；对外服务时建议显式设为 true。
    login_rate_limit_enabled: bool = False
    login_rate_limit_requests: int = 5
    login_rate_limit_window: int = 900
    # 不参与限流的路径前缀
    rate_limit_exempt_paths: str = "/health,/docs,/redoc,/openapi.json,/ui,/static"
    # 是否信任 X-Forwarded-For 头来识别客户端 IP（仅在可信反向代理之后才应开启，
    # 否则客户端可伪造该头绕过限流）
    trust_forwarded_for: bool = False

    # ---------- 大模型 / OpenAI 兼容接口 ----------
    # 支持官方 OpenAI、本地 Ollama、以及各类兼容 OpenAI 协议的第三方服务
    # 环境变量同时认 OPENAI_API_KEY（标准）和 DEEPSEEK_API_KEY（很多用户的习惯命名）
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "DEEPSEEK_API_KEY"),
    )
    # 例：官方 https://api.openai.com/v1 ；Ollama http://localhost:11434/v1 ；
    #     DeepSeek https://api.deepseek.com 或 https://api.deepseek.com/v1
    openai_base_url: str = "https://api.openai.com/v1"
    # 使用的模型名，例：gpt-4o-mini / qwen2.5:7b / deepseek-chat / deepseek-flash
    model_name: str = "gpt-4o-mini"

    # ---------- 本地 Ollama（前端可选择，不向浏览器暴露任何密钥） ----------
    # Ollama 提供 OpenAI 兼容的 /v1 接口；本机默认无需真实 API Key。
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model_name: str = "qwen2.5:7b-instruct-q4_K_M"

    # 模型调用参数
    temperature: float = 0.7
    max_tokens: int = 1024
    request_timeout: int = 60  # 单次请求超时（秒）

    # ---------- LLM 弹性（重试 + 熔断） ----------
    # 可恢复错误的最大重试次数（429/5xx/超时）
    llm_retry_attempts: int = 3
    # 指数退避的初始延迟（秒），后续按 2^n 翻倍
    llm_retry_base_delay: float = 0.5
    # 单次重试的最大延迟上限（秒）
    llm_retry_max_delay: float = 4.0
    # 熔断器阈值：连续失败次数
    llm_circuit_threshold: int = 5
    # 熔断后冷却时长（秒）
    llm_circuit_reset_s: float = 30.0

    # ---------- 多轮上下文压缩 ----------
    # 单会话触发历史摘要的阈值（消息条数 = user/assistant 各 1 = 2 条一对）
    context_summary_trigger: int = 16
    # 摘要保留的最近消息条数（其余被摘要成 1 条 system 消息）
    context_summary_keep_recent: int = 6
    # 摘要的目标字数（中文）
    context_summary_target_chars: int = 200
    # 是否启用上下文压缩（关闭则只丢早期消息，不调 LLM 摘要）
    enable_context_summary: bool = True
    # 单会话最多摘要次数（防止反复触发消耗 token）
    context_summary_max_per_session: int = 1

    # ---------- 离线 ASR（faster-whisper） ----------
    # 是否启用 /chat/audio 端点；关闭时端点直接返回 503
    asr_enabled: bool = True
    # 模型大小：tiny/base/small/medium/large-v3（small ~460MB、medium ~1.5GB）
    asr_model_size: str = "small"
    # 模型下载到本地的目录（默认 ~/.cache/huggingface）
    asr_model_dir: str = ""
    # 推理设备：auto/cpu/cuda
    asr_device: str = "auto"
    # 量化精度：int8/float16/float32（int8 体积小一半，速度略降）
    asr_compute_type: str = "int8"
    # 默认源语言（zh/en/auto）
    asr_language: str = "auto"
    # 单次请求最大音频秒数（前端录音时长软上限）
    asr_max_duration_s: int = 60
    # HTTP 音频上传硬上限，防止超大文件耗尽内存/磁盘。
    asr_max_upload_bytes: int = 10 * 1024 * 1024
    # WebSocket 音频流的累计字节及并发上限，防止绕过 HTTP 上传限制。
    asr_stream_max_bytes: int = 10 * 1024 * 1024
    asr_stream_max_connections: int = 2
    # 模型名（huggingface 上的仓库 ID），用于 faster-whisper 在 asr_model_dir 中查找模型文件
    asr_repo_id: str = "Systran/faster-whisper-%s"

    # ---------- 检索 / 知识库 ----------
    # 检索后端：
    #   tfidf     —— 轻量方案，中文 TF-IDF / 字符 n-gram，零额外依赖（默认）
    #   embedding —— sentence-transformers + FAISS（需额外安装，语义检索效果好）
    #   auto      —— 优先 embedding，依赖缺失时自动回退 tfidf
    retriever_backend: str = "tfidf"
    # embedding 后端使用的模型（需支持中文；仅 backend=embedding/auto 时生效）
    embedding_model: str = "shibing624/text2vec-base-chinese"
    # 知识库检索返回的 FAQ 条数
    faq_top_k: int = 3
    # 检索得分下限：低于该值时认为知识库未命中
    faq_min_score: float = 0.15
    # FAQ 检索结果缓存 TTL（秒）；0 = 不缓存
    faq_cache_ttl_seconds: float = 300.0
    # FAQ 缓存容量上限（按条目数；超过后按 LRU 淘汰）
    faq_cache_max_size: int = 1024

    # ---------- 意图识别 ----------
    # 规则未命中时是否调用大模型做兜底分类
    intent_use_llm: bool = True

    # ---------- 日志 ----------
    log_level: str = "INFO"

    # ---------- 派生属性 ----------
    @property
    def origins_list(self) -> list[str]:
        """将逗号分隔的 CORS 来源解析为列表。"""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def data_path(self) -> Path:
        """数据目录的绝对路径（相对路径以项目根目录为基准）。"""
        p = Path(self.data_dir)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def log_db_file(self) -> Path:
        """SQLite 日志文件的绝对路径。"""
        p = Path(self.log_db_path)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def rate_limit_exempt_list(self) -> list[str]:
        """解析免限流路径前缀。"""
        return [p.strip() for p in self.rate_limit_exempt_paths.split(",") if p.strip()]

    @property
    def llm_configured(self) -> bool:
        """是否已配置大模型 API Key。"""
        return bool(self.openai_api_key.strip())

    @property
    def admin_keys(self) -> set[str]:
        """合并单 key 和多 key（去重 + 去空），用于 admin 鉴权。"""
        keys = set()
        for raw in (self.admin_api_key, self.admin_api_keys):
            for k in raw.split(","):
                k = k.strip()
                if k:
                    keys.add(k)
        return keys

    @property
    def admin_enabled(self) -> bool:
        """是否启用了 admin 鉴权（任一 key 配置即视为启用）。"""
        return bool(self.admin_keys)

    @property
    def is_production(self) -> bool:
        """是否为需要强制安全配置的部署环境。"""
        return self.app_env.strip().lower() in {"production", "staging"}

    def security_configuration_errors(self) -> list[str]:
        """返回生产环境不允许的危险配置，供启动阶段 fail-fast。"""
        if not self.is_production:
            return []

        errors = []
        if self.debug:
            errors.append("生产环境必须设置 DEBUG=false")
        if not self.auth_enabled:
            errors.append("生产环境不允许关闭 AUTH_ENABLED")
        if len(self.auth_secret.strip()) < 32:
            errors.append("生产环境必须配置长度至少 32 的 AUTH_SECRET")
        if not self.admin_enabled:
            errors.append("生产环境必须配置 ADMIN_API_KEY 或 ADMIN_API_KEYS")
        if "null" in self.origins_list:
            errors.append("生产环境的 ALLOWED_ORIGINS 不允许包含 null")
        return errors


@lru_cache
def get_settings() -> Settings:
    """获取配置单例（带缓存）。"""
    return Settings()


settings = get_settings()
