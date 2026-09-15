#!/bin/sh
# Container entrypoint (Alpine)
# 默认主镜像（Dockerfile alpline）专用

WITH_ASR="${WITH_ASR:-0}"

echo "=== ecommerce-ai-customer-service (alpine) ==="
echo "Image: alpine-based, ~175MB"
echo "ASR: not bundled (ctranslate2 has no musl wheel)"
echo "     /chat/audio returns 503; rebuild with -f Dockerfile.slim --build-arg WITH_ASR=1 to enable."
exec "$@"
