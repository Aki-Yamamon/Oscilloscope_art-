"""ESP32 の動作確認用の .osa を作る（回る四角 + 中央の円）。

    python scripts/make_test.py -o test.osa --seconds 5

動画が無くても作れるので、ファームウェアの開発を先に進められる。
path.py の関数をそのまま使うので、path.py の確認にもなる。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from osaconv.pack import OsaWriter
from osaconv.path import contours_to_path

SIZE = 256   # 仮想的な画像サイズ（256 x 256）


def square(angle: float, half: float = 80.0) -> np.ndarray:
    """中心 (128,128) を回る正方形。閉じた (5, 2) float32。"""
    corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=np.float64) * half
    c, s = np.cos(angle), np.sin(angle)
    rot = np.array([[c, -s], [s, c]])
    pts = corners @ rot.T + 127.5
    return np.vstack([pts, pts[:1]]).astype(np.float32)


def circle(radius: float = 25.0, n: int = 40) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n, endpoint=True)
    return np.stack([127.5 + radius * np.cos(t), 127.5 + radius * np.sin(t)], axis=1).astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="test.osa")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--points", type=int, default=1000)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--period", type=float, default=4.0, help="1 周する秒数")
    args = ap.parse_args()

    frames = int(args.seconds * args.fps)
    with OsaWriter(args.out, fps=args.fps, points_per_frame=args.points) as w:
        for i in range(frames):
            angle = 2 * np.pi * (i / args.fps) / args.period
            path = contours_to_path([square(angle), circle()], (SIZE, SIZE), args.points)
            w.write_frame(path)
    print(f"saved: {args.out} ({frames} frames, {Path(args.out).stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
