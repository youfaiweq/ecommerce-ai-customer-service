#!/bin/sh
# Container entrypoint：打印 ASR 状态后再 exec 主进程
# 接受 ARG WITH_ASR + PRELOAD_MODEL（运行时通过 image label / env 传入）

WITH_ASR="${WITH_ASR:-0}"
PRELOAD_MODEL="${PRELOAD_MODEL:-0}"
ASR_MODEL_SIZE="${ASR_MODEL_SIZE:-small}"

echo "=== ecommerce-ai-customer-service (slim+ASR) ==="
echo "Image built with WITH_ASR=${WITH_ASR} PRELOAD_MODEL=${PRELOAD_MODEL} ASR_MODEL_SIZE=${ASR_MODEL_SIZE}"
echo "ASR status:"
if [ "${WITH_ASR}" = "1" ]; then
  echo "  enabled by build"
  if [ "${PRELOAD_MODEL}" = "1" ] && [ -d /home/app/.cache/huggingface/hub ]; then
    cached=$(du -sh /home/app/.cache/huggingface/hub 2>/dev/null | cut -f1 || echo "?")
    echo "  preloaded: ${cached} cached at /home/app/.cache/huggingface"
    echo "  → first /chat/audio request will skip model download"
  else
    echo "  not preloaded; first /chat/audio request will download ${ASR_MODEL_SIZE} (~460MB)"
    echo "  cache dir: ${HF_HOME:-/home/app/.cache/huggingface}"
  fi
else
  echo "  disabled (build with --build-arg WITH_ASR=1 to enable)"
  echo "  /chat/audio will return 503 asr_disabled at runtime"
fi
exec "$@"
