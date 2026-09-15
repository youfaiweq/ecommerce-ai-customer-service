"""生成 ASR 端点冒烟测试用 wav：2 秒 16kHz mono，前 0.5s 静音 + 1s 440Hz tone + 0.5s 静音。
用 stdlib wave 写 16-bit PCM，无需第三方依赖。
"""
import math
import struct
import wave

OUT = "test_tone.wav"
SR = 16000
DUR_S = 2.0
N = int(SR * DUR_S)

with wave.open(OUT, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    frames = bytearray()
    for i in range(N):
        t = i / SR
        if 0.5 <= t < 1.5:
            v = 0.3 * math.sin(2 * math.pi * 440 * t)
        else:
            v = 0.0
        frames += struct.pack("<h", int(v * 32767))
    w.writeframes(bytes(frames))
print(f"OK {N} samples")
