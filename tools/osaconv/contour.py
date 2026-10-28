"""輪郭抽出モジュール。

グレースケール画像 1 枚から、輪郭の点列（ピクセル座標）を取り出す。
座標は元画像のピクセル座標のまま返す。0〜255 への変換は path.py の担当。

処理の流れ:
    gray ──(_binarize)──> 二値画像 ──(_find_raw)──> 生の輪郭
         ──(_simplify)──> 点を間引いた輪郭 ──(_to_closed_xy)──> (M, 2) float32
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ContourParams:
    """輪郭抽出の設定値。"""

    threshold: int | None = None     # None なら大津法（しきい値を自動決定）
    invert: bool = False             # True なら白黒を反転してから輪郭を探す
    blur_ksize: int = 0              # 0 ならぼかさない。ぼかすなら奇数（3, 5, ...）
    epsilon: float = 1.0             # 輪郭の簡略化の強さ（ピクセル）。大きいほど点が減る
    min_length: float = 20.0         # 周の長さがこれ未満の輪郭は捨てる（ピクセル）
    retrieval: int = cv2.RETR_LIST   # RETR_LIST: 全部 / RETR_EXTERNAL: 外側だけ


def _binarize(gray: np.ndarray, params: ContourParams) -> np.ndarray:
    """グレースケール画像を二値画像（0 か 255）にする。

    findContours は「白い部分」を物体として輪郭を探す。
    invert=True にすると、暗い部分が白（255）になる。
    """
    if params.blur_ksize > 0:
        k = params.blur_ksize
        if k % 2 == 0:
            raise ValueError(f"blur_ksize は奇数にしてください: {k}")
        gray = cv2.GaussianBlur(gray, (k, k), 0)

    flags = cv2.THRESH_BINARY_INV if params.invert else cv2.THRESH_BINARY
    if params.threshold is None:
        flags |= cv2.THRESH_OTSU     # このとき thresh の値は無視される
        thresh = 0
    else:
        thresh = params.threshold

    _, binary = cv2.threshold(gray, thresh, 255, flags)
    return binary


def _find_raw(binary: np.ndarray, retrieval: int) -> list[np.ndarray]:
    """二値画像から輪郭を探す。各要素は (M, 1, 2) int32（OpenCV の生の形式）。"""
    contours, _hierarchy = cv2.findContours(binary, retrieval, cv2.CHAIN_APPROX_NONE)
    return list(contours)


def _simplify(contour: np.ndarray, epsilon: float) -> np.ndarray:
    """輪郭の点を間引く（ダグラス・ポイカー法）。(M,1,2) int32 → (K,1,2) int32。"""
    return cv2.approxPolyDP(contour, epsilon, True)


def _to_closed_xy(contour: np.ndarray) -> np.ndarray:
    """(K,1,2) int32 を (K+1, 2) float32 にする。最後の点 = 最初の点（閉じる）。"""
    pts = contour.reshape(-1, 2).astype(np.float32)
    return np.vstack([pts, pts[0]])


def frame_to_contours(
    gray: np.ndarray,
    params: ContourParams | None = None,
) -> list[np.ndarray]:
    """グレースケール画像から輪郭の点列を取り出す。

    引数:
        gray: shape (H, W)、dtype uint8 のグレースケール画像
        params: 設定値。None なら既定値

    戻り値:
        輪郭ごとの (M, 2) float32 配列のリスト。1 行が [x, y]。
        座標は元画像のピクセル座標（原点は左上、y は下向きが正）。
        閉じた輪郭（最後の点 = 最初の点）。輪郭が無ければ空のリスト。
    """
    if params is None:
        params = ContourParams()
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError(
            f"gray は (H, W) の uint8 が必要です: shape={gray.shape}, dtype={gray.dtype}"
        )

    binary = _binarize(gray, params)
    out: list[np.ndarray] = []
    for raw in _find_raw(binary, params.retrieval):
        simple = _simplify(raw, params.epsilon)
        if len(simple) < 2:
            continue
        if cv2.arcLength(simple, True) < params.min_length:
            continue
        out.append(_to_closed_xy(simple))
    return out
