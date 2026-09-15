"""下载 faster-whisper 模型到本地，方便后续 COPY 进 Docker 镜像。

用法：
    python tools/download_asr_model.py [tiny|base|small|medium|large-v3]

默认 small（~460MB）。下载完成后模型会落在 ``models/hf-cache/`` 下，
可直接 ``COPY --from=models ./models/hf-cache /home/app/.cache/huggingface`` 烤进镜像。
"""
import os
import sys
from pathlib import Path

# 固定到项目内：避免污染用户主目录，也方便 Docker COPY
ROOT = Path(__file__).resolve().parent.parent
HF_HOME = ROOT / "models" / "hf-cache"
HF_HOME.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HOME / "hub")
# 不写 ~/.cache/huggingface
os.environ["XDG_CACHE_HOME"] = str(HF_HOME)

size = sys.argv[1] if len(sys.argv) > 1 else "small"
device = sys.argv[2] if len(sys.argv) > 2 else "cpu"
compute = sys.argv[3] if len(sys.argv) > 3 else "int8"

print(f"Downloading faster-whisper {size} → {HF_HOME}")
print(f"device={device}, compute_type={compute}")

from faster_whisper import WhisperModel  # noqa: E402

model = WhisperModel(size, device=device, compute_type=compute, model_dir=str(HF_HOME / "hub"))
print(f"Loaded: {size}")

# 触发下载：读 .name 强制 hub 走一遍
print("Hub dir:", HF_HOME / "hub")
for p in (HF_HOME / "hub").rglob("*"):
    if p.is_file():
        size_kb = p.stat().st_size // 1024
        print(f"  {p.relative_to(HF_HOME)}  ({size_kb} KB)")
print("DONE")
