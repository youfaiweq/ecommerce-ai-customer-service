# =============================================================================
# 主 Dockerfile（默认）：Alpine 基础，目标 < 200MB
#
# ⚠️  本镜像**不含** faster-whisper（ctranslate2 没有 musl 官方 wheel，
#     如需 ASR 请改用 ``Dockerfile.slim`` 构建，体积约 ~580MB）。
#
# 体积预估：
#   - python:3.13-alpine               ~80MB
#   - site-packages (8 deps)           ~80MB  (其中 openai SDK 24MB / uvloop 16MB)
#   - application code                   1MB
#   - 其它（tini/curl/tzdata/glibc）   ~30MB
#   - 共：约 175-190MB
# =============================================================================
FROM python:3.13-alpine AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY requirements.txt ./

# 主依赖（always）
RUN apk add --no-cache \
        gcc musl-dev linux-headers \
    && pip install --prefix=/install -r requirements.txt \
    && apk del gcc musl-dev linux-headers


# =============================================================================
# Runtime stage
# =============================================================================
FROM python:3.13-alpine AS runtime

# tini = init / 信号转发；curl = HEALTHCHECK；tzdata = 设置时区
# glibc compat layer 让 uvloop（musl-only wheel）也能跑
RUN apk add --no-cache tini curl tzdata \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

# 非 root 用户
RUN addgroup -S app && adduser -S -G app -h /home/app app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PATH="/usr/local/bin:${PATH}" \
    TZ=Asia/Shanghai

WORKDIR /app

COPY --from=builder /install/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /install/bin /usr/local/bin

COPY --chown=app:app app/ ./app/
COPY --chown=app:app data/ ./data/
COPY --chown=app:app frontend/ ./frontend/

# 清理 pip / 测试 / __pycache__ / 文档
RUN find /usr/local/lib/python3.13/site-packages \
        \( -type d -name '__pycache__' -o -type d -name 'tests' -o -type d -name 'test' \) \
        -exec rm -rf {} + 2>/dev/null || true \
    && find /usr/local/lib/python3.13/site-packages \
        -name '*.pyc' -o -name '*.pyo' \
        -delete 2>/dev/null || true \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* /usr/local/share/man

# entrypoint 脚本：打印 ASR 状态后再 exec CMD
COPY --chown=root:root docker-entrypoint-alpine.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

USER app

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
