#!/usr/bin/env bash
# =============================================================================
# 端到端 ASR 验证脚本：在你自己机器上一键跑通"预烤 ASR 模型 → 启动 → 真实转写"
#
# 用法：
#   bash scripts/verify-asr-e2e.sh                 # 预烤 base 模型（推荐，速度最快）
#   ASR_MODEL_SIZE=small bash scripts/verify-asr-e2e.sh
#                                                # 用 small 模型（更准，但镜像多 ~320MB）
#   SKIP_PRELOAD=1 bash scripts/verify-asr-e2e.sh # 跳过预烤，运行时按需下载
#   SKIP_BUILD=1   bash scripts/verify-asr-e2e.sh # 复用已有镜像，跳过 build
#   KEEP=1         bash scripts/verify-asr-e2e.sh # 验证完不清理容器（方便调试）
#
# 退出码：
#   0 = 全部通过；非 0 = 某一步失败（脚本会打印失败步骤）
#
# 平台：Linux / macOS / Git Bash on Windows（需 docker + curl + python3）
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
ASR_MODEL_SIZE="${ASR_MODEL_SIZE:-base}"
COMPOSE_PROJECT="ecs-verify-e2e"
CONTAINER_NAME="ecs-verify-e2e-asr"
HOST_PORT="${HOST_PORT:-8124}"
IMAGE_TAG="ecs-verify:asr-${ASR_MODEL_SIZE}"
LOG_DIR="${LOG_DIR:-./.verify-logs}"

# 颜色（如果终端支持）
if [[ -t 1 ]]; then
  C_OK="\033[32m"; C_BAD="\033[31m"; C_INFO="\033[36m"; C_WARN="\033[33m"; C_RST="\033[0m"
else
  C_OK=""; C_BAD=""; C_INFO=""; C_WARN=""; C_RST=""
fi
log()  { printf "${C_INFO}[$(date +%H:%M:%S)]${C_RST} %s\n" "$*"; }
ok()   { printf "${C_OK}[ OK ]${C_RST} %s\n"  "$*"; }
warn() { printf "${C_WARN}[WARN]${C_RST} %s\n" "$*"; }
bad()  { printf "${C_BAD}[FAIL]${C_RST} %s\n" "$*"; exit 1; }

# ----------------------------------------------------------------------------
# 步骤 1：环境检查
# ----------------------------------------------------------------------------
log "1/7 检查环境..."

if ! command -v docker >/dev/null 2>&1; then
  bad "未检测到 docker，请先安装 Docker Desktop / docker-ce"
fi
docker info >/dev/null 2>&1 || bad "Docker daemon 不可访问（Linux 用户：systemctl start docker）"
ok "Docker 可用：$(docker --version)"

if ! command -v curl >/dev/null 2>&1; then
  bad "未检测到 curl，请安装 curl"
fi
ok "curl 可用"

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  bad "未检测到 python3 / python（用于生成测试音频）"
fi
PY="${PY:-$(command -v python3 2>/dev/null || command -v python 2>/dev/null)}"
ok "Python 可用：$PY"

mkdir -p "$LOG_DIR"

# ----------------------------------------------------------------------------
# 步骤 2：预烤镜像
# ----------------------------------------------------------------------------
if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
  log "2/7 跳过 build（SKIP_BUILD=1），复用镜像 $IMAGE_TAG"
  if ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    bad "镜像 $IMAGE_TAG 不存在，请去掉 SKIP_BUILD=1 重新运行"
  fi
else
  log "2/7 构建镜像（PRELOAD_MODEL=1，ASR_MODEL_SIZE=$ASR_MODEL_SIZE）..."
  log "    此步会从 HuggingFace 下载 ASR 模型（base ≈ 140MB，small ≈ 460MB）"
  log "    网络不好可设 HF_ENDPOINT=https://hf-mirror.com 加速"

  # 用 Dockerfile.slim，预烤模型
  # 注意：预下载失败不会让 build 失败（Dockerfile 已经 || true 兜底）
  docker build \
    -f Dockerfile.slim \
    --build-arg WITH_ASR=1 \
    --build-arg PRELOAD_MODEL="${SKIP_PRELOAD_PRE:-1}" \
    --build-arg ASR_MODEL_SIZE="$ASR_MODEL_SIZE" \
    -t "$IMAGE_TAG" \
    . 2>&1 | tee "$LOG_DIR/build.log" | tail -30

  ok "镜像构建完成：$IMAGE_TAG"
  if [[ "${SKIP_PRELOAD_PRE:-1}" == "1" ]]; then
    log "    预烤日志（看 'Preloaded ASR models:' 那行确认缓存大小）："
    grep -A 3 "Preloaded ASR models" "$LOG_DIR/build.log" || warn "未找到预烤成功的日志（可能构建环境无 HF 网络，但 build 不会失败）"
  fi
fi

# ----------------------------------------------------------------------------
# 步骤 3：清理上次残留
# ----------------------------------------------------------------------------
log "3/7 清理上一次残留的容器..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
ok "环境干净"

# ----------------------------------------------------------------------------
# 步骤 4：启动容器
# ----------------------------------------------------------------------------
log "4/7 启动容器（端口 ${HOST_PORT}，data 目录挂载到 ./data）..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "${HOST_PORT}:8000" \
  -e DATA_DIR=data \
  -e LOG_DB_PATH=data/app.db \
  -e DEBUG=true \
  -e ASR_ENABLED=true \
  -e ASR_MODEL_SIZE="$ASR_MODEL_SIZE" \
  -e TZ=Asia/Shanghai \
  -v "$(pwd)/data:/app/data" \
  "$IMAGE_TAG" > "$LOG_DIR/run.log" 2>&1
ok "容器已起：$(cat "$LOG_DIR/run.log")"

# 等待 healthy（最多 90s，因为 small 模型首次启动要 +5-10s 加载 ctranslate2）
log "    等待容器 healthy（最多 90s）..."
for i in $(seq 1 45); do
  status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "starting")
  if [[ "$status" == "healthy" ]]; then
    ok "容器 healthy（第 $(( i * 2 ))s）"
    break
  fi
  if (( i == 45 )); then
    bad "容器 90s 内未 healthy，请查看 $LOG_DIR/run.log + docker logs $CONTAINER_NAME"
  fi
  sleep 2
done

# ----------------------------------------------------------------------------
# 步骤 5：检查 /asr/status
# ----------------------------------------------------------------------------
log "5/7 验证 /asr/status..."
ASR_BODY=$(curl -fsS "http://127.0.0.1:${HOST_PORT}/asr/status")
echo "    响应：$ASR_BODY"

echo "$ASR_BODY" | $PY -c "
import json, sys
d = json.loads(sys.stdin.read())
assert d.get('enabled') is True,           f'enabled 应当 True，实际 {d.get(\"enabled\")}'
assert d.get('model_size') == '$ASR_MODEL_SIZE', f'model_size 应当 $ASR_MODEL_SIZE，实际 {d.get(\"model_size\")}'
assert 'load_attempts' in d, '缺 load_attempts 字段'
loaded = d.get('loaded')
print(f'    loaded={loaded}  (PRELOAD_MODEL=1 时应 True)')
"
ok "/asr/status 结构正确"

# ----------------------------------------------------------------------------
# 步骤 6：上传一段测试音频，让 faster-whisper 真实转写
# ----------------------------------------------------------------------------
log "6/7 生成测试音频并上传转写..."
AUDIO_FILE="$LOG_DIR/test_tone.wav"
$PY - "$AUDIO_FILE" <<'PYEOF'
"""生成一段 3 秒的"测试音频"：1kHz 正弦 + 静音段。
转写模型可能识别不到语义，但应正常返回（非错误），从而验证完整链路。
"""
import math, struct, sys, wave

out, sr, dur = sys.argv[1], 16000, 3.0
n = int(sr * dur)
with wave.open(out, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    frames = bytearray()
    for i in range(n):
        t = i / sr
        # 0.0–0.5s 静音; 0.5–2.5s 1kHz tone; 2.5–3.0s 静音
        if 0.5 <= t < 2.5:
            v = 0.3 * math.sin(2 * math.pi * 1000 * t)
        else:
            v = 0.0
        frames += struct.pack('<h', int(v * 32767))
    w.writeframes(bytes(frames))
print(f"    生成 {out}: {n} samples @ {sr} Hz ({dur}s)")
PYEOF

log "    上传到 /chat/audio（首次会做实际推理，3-5s）..."
RESP=$(curl -fsS -X POST \
  -F "file=@${AUDIO_FILE};type=audio/wav" \
  "http://127.0.0.1:${HOST_PORT}/chat/audio")
echo "    响应：$RESP"

echo "$RESP" | $PY -c "
import json, sys
d = json.loads(sys.stdin.read())
assert 'text' in d,         f'缺 text 字段：{d}'
assert 'language' in d,     f'缺 language 字段：{d}'
assert 'duration_s' in d,   f'缺 duration_s 字段：{d}'
print(f'    text=\"{d[\"text\"]}\"  language={d[\"language\"]}  duration_s={d[\"duration_s\"]}')
print('    ✅ ASR 端到端真实转写通过！')
"

# ----------------------------------------------------------------------------
# 步骤 7：清理
# ----------------------------------------------------------------------------
if [[ "${KEEP:-0}" == "1" ]]; then
  log "7/7 KEEP=1：保留容器方便调试（docker rm -f $CONTAINER_NAME 手动清理）"
  log "    日志目录：$LOG_DIR  |  容器：$CONTAINER_NAME  |  镜像：$IMAGE_TAG"
else
  log "7/7 清理临时容器和镜像..."
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    docker rmi "$IMAGE_TAG" >/dev/null 2>&1 || true
  fi
  ok "已清理"
fi

# ----------------------------------------------------------------------------
log ""
log "${C_OK}=== 全部验证通过！==="
log "现在你可以:"
log "  1. 真机使用：docker compose --profile asr up -d --build"
log "  2. 看日志：  cd $LOG_DIR  &&  cat build.log run.log"
log "  3. 集成 GHCR 镜像：pull ghcr.io/<owner>/<repo>/ecs:asr-base（或 asr-small）"
