"""輪郭抽出のパラメータを、スライダーで動かしながら確認するツール。

使い方（tools/ ディレクトリで実行）:
    python scripts/tune_contour.py badapple.mp4 --frame 1000
    python scripts/tune_contour.py picture.png

画面は 3 枚並び: [元画像] [二値化後] [輪郭を重ねた画像]
キー:  q = 終了 / p = 今のパラメータを表示 / s = 画面を保存 / ←→ や a,d = 前後のフレーム（動画のみ）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ から osaconv を import できるようにする（tools/ を import の探索先に追加）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from osaconv.contour import ContourParams, _binarize, frame_to_contours

WINDOW = "tune_contour"


def load_gray(source: str, frame_index: int) -> tuple[np.ndarray, cv2.VideoCapture | None]:
    """画像ファイルまたは動画の 1 フレームを、グレースケールで読み込む。"""
    if not Path(source).exists():
        raise FileNotFoundError(source)
    img = cv2.imread(source, cv2.IMREAD_GRAYSCALE)
    if img is not None:                       # 画像ファイルだった
        return img, None
    cap = cv2.VideoCapture(source)            # 動画だった
    if not cap.isOpened():
        raise RuntimeError(f"開けませんでした: {source}")
    return read_frame(cap, frame_index), cap


def read_frame(cap: cv2.VideoCapture, index: int) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"フレーム {index} を読めませんでした")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def build_view(gray: np.ndarray, params: ContourParams) -> tuple[np.ndarray, int, int]:
    """3 枚並びの表示画像と、輪郭の本数・総点数を作る（画面を開かずにテストできる）。"""
    binary = _binarize(gray, params)
    contours = frame_to_contours(gray, params)

    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    # 輪郭は (M,2) float32。drawContours は (M,1,2) int32 を求めるので形を直す
    drawable = [c.astype(np.int32).reshape(-1, 1, 2) for c in contours]
    cv2.drawContours(overlay, drawable, -1, (0, 255, 0), 1)

    left = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    mid = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    view = np.hstack([left, mid, overlay])

    n_contours = len(contours)
    n_points = int(sum(len(c) for c in contours))
    return view, n_contours, n_points


def params_from_trackbars() -> ContourParams:
    """スライダーの位置から ContourParams を作る。"""
    th = cv2.getTrackbarPos("threshold (0=Otsu)", WINDOW)
    blur = cv2.getTrackbarPos("blur (0=off)", WINDOW)
    return ContourParams(
        threshold=None if th == 0 else th,
        invert=bool(cv2.getTrackbarPos("invert", WINDOW)),
        blur_ksize=0 if blur == 0 else 2 * blur + 1,          # 1→3, 2→5, 3→7 ...
        epsilon=cv2.getTrackbarPos("epsilon x0.1", WINDOW) / 10.0,
        min_length=float(cv2.getTrackbarPos("min_length", WINDOW)),
        retrieval=cv2.RETR_EXTERNAL if cv2.getTrackbarPos("external only", WINDOW) else cv2.RETR_LIST,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("source", help="画像または動画のパス")
    ap.add_argument("--frame", type=int, default=0, help="動画のとき、見るフレーム番号")
    ap.add_argument("--width", type=int, default=1500, help="表示の横幅（画面に収まらないとき小さくする）")
    args = ap.parse_args()

    frame_index = args.frame
    gray, cap = load_gray(args.source, frame_index)

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    nop = lambda _v: None                                    # スライダーの変更時には何もしない
    cv2.createTrackbar("threshold (0=Otsu)", WINDOW, 0, 255, nop)
    cv2.createTrackbar("invert", WINDOW, 0, 1, nop)
    cv2.createTrackbar("blur (0=off)", WINDOW, 0, 5, nop)
    cv2.createTrackbar("epsilon x0.1", WINDOW, 10, 100, nop)   # 10 → epsilon 1.0
    cv2.createTrackbar("min_length", WINDOW, 20, 200, nop)
    cv2.createTrackbar("external only", WINDOW, 0, 1, nop)

    while True:
        params = params_from_trackbars()
        view, n_c, n_p = build_view(gray, params)
        scale = args.width / view.shape[1]
        if scale < 1.0:
            view = cv2.resize(view, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        text = f"frame={frame_index}  contours={n_c}  points={n_p}"
        cv2.putText(view, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imshow(WINDOW, view)

        key = cv2.waitKey(30) & 0xFF
        if key == ord("q") or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        elif key == ord("p"):
            print(params, f"  -> contours={n_c} points={n_p}")
        elif key == ord("s"):
            out = f"tune_{frame_index}.png"
            cv2.imwrite(out, view)
            print("saved:", out)
        elif cap is not None and key in (ord("d"), 83):       # d か → で次へ
            frame_index += 1
            gray = read_frame(cap, frame_index)
        elif cap is not None and key in (ord("a"), 81):       # a か ← で前へ
            frame_index = max(0, frame_index - 1)
            gray = read_frame(cap, frame_index)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
