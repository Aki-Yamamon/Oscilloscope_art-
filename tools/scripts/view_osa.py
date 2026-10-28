"""できあがった .osa の中身を、PC 上で絵として確認する。

    python scripts/view_osa.py out.osa                 # 画面に表示
    python scripts/view_osa.py out.osa --save a.png    # 画像に保存
    python scripts/view_osa.py out.osa --count 12      # 12 枚並べる

オシロスコープに出る絵を、線でつないだ形で表示する。
つなぎ線（輪郭と輪郭の間の線）も含めて見えるので、実機で見える姿に近い。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from osaconv.pack import read_osa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("osa")
    ap.add_argument("--count", type=int, default=6, help="並べるフレーム数")
    ap.add_argument("--save", help="指定すると画像に保存して終了")
    args = ap.parse_args()

    import matplotlib
    if args.save:
        matplotlib.use("Agg")           # 画面を開かずに描く
    import matplotlib.pyplot as plt

    header, xy, _ = read_osa(args.osa)
    print(header)
    idxs = np.linspace(0, header.frame_count - 1, args.count).astype(int)

    cols = min(3, args.count)
    rows = -(-args.count // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows), squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, i in zip(axes.ravel(), idxs):
        pts = xy[i]
        ax.plot(pts[:, 0], pts[:, 1], "-", lw=0.6, color="tab:green")
        ax.set_xlim(0, 255)
        ax.set_ylim(0, 255)
        ax.set_aspect("equal")
        ax.set_facecolor("black")
        ax.set_title(f"frame {i}", fontsize=9)
        ax.axis("on")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout()

    if args.save:
        fig.savefig(args.save, dpi=100)
        print("saved:", args.save)
    else:
        plt.show()


if __name__ == "__main__":
    main()
