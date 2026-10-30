"""音と映像のずれを測るための、テスト用データを作る。

    python scripts/make_sync_test.py            # sync_test.osa と sync_test.wav ができる
    python -m osaconv.play sync_test.osa --audio sync_test.wav --port COM6 --loop

1 秒ごとに、「ピッ」という音と、画面の「大きな四角のフラッシュ」が同時に出るはず（0.1 秒間）。
それ以外のときは、小さな円が出る。スマホで、オシロ画面とスピーカーを一緒に動画撮影し、
コマ送りで「音が出たコマ」と「四角が出たコマ」を比べると、ずれが分かる。
"""
import argparse
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from osaconv.pack import OsaWriter
from osaconv.path import contours_to_path

SIZE = 256


def circle(radius: float, n: int = 60) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n)
    return np.stack([127.5 + radius * np.cos(t), 127.5 + radius * np.sin(t)], axis=1).astype(np.float32)


def square(half: float) -> np.ndarray:
    c = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]], dtype=np.float32) * half + 127.5
    return c.astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--points", type=int, default=1000)
    ap.add_argument("--rate", type=int, default=44100)
    ap.add_argument("--osa", default="sync_test.osa")
    ap.add_argument("--wav", default="sync_test.wav")
    args = ap.parse_args()

    small = contours_to_path([circle(25)], (SIZE, SIZE), args.points)
    big = contours_to_path([square(110), circle(60)], (SIZE, SIZE), args.points)
    flash_frames = max(round(0.1 * args.fps), 1)             # 0.1 秒
    with OsaWriter(args.osa, fps=args.fps, points_per_frame=args.points) as w:
        for i in range(args.seconds * args.fps):
            w.write_frame(big if (i % args.fps) < flash_frames else small)

    n = args.seconds * args.rate
    audio = np.zeros(n, dtype=np.int16)
    beep_len = int(0.1 * args.rate)
    t = np.arange(beep_len) / args.rate
    beep = (0.5 * 32767 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16)
    for s in range(args.seconds):
        audio[s * args.rate: s * args.rate + beep_len] = beep
    with wave.open(args.wav, "wb") as wv:
        wv.setnchannels(1)
        wv.setsampwidth(2)
        wv.setframerate(args.rate)
        wv.writeframes(audio.tobytes())
    print(f"saved: {args.osa}, {args.wav}（{args.seconds} 秒、毎秒 0.1 秒のフラッシュ + ビープ）")


if __name__ == "__main__":
    main()
