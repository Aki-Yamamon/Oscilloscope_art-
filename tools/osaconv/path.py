"""輪郭の点列を、ESP32 に渡す「1 本の経路（N 点、値は 0〜255）」にする。

処理の流れ:
    contours（ピクセル座標）
      ──(_to_dac_space)──> DAC 座標（0〜255、y は上向きが正）
      ──(_order_and_join)──> 1 本につないだ折れ線
      ──(_resample)──────> 弧長が等間隔な N 点
      ──(丸めて uint8)───> (N, 2) uint8

オシロスコープにはビームを消す機能（Z 軸）が無いので、輪郭と輪郭の間も線で結ばれて見える。
その「つなぎ線」を短くするため、今いる位置に近い輪郭から順に回る（最近傍法）。
"""
from __future__ import annotations

import numpy as np

DAC_MAX = 255.0     # DAC の最大値（8bit）
DAC_CENTER = 128    # 輪郭が無いフレームでビームを置く位置


def _polyline_length(pts: np.ndarray) -> float:
    """折れ線の長さ。pts は (M, 2)。"""
    return float(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])).sum())


def _to_dac_space(contours: list[np.ndarray], frame_shape: tuple[int, int]) -> list[np.ndarray]:
    """ピクセル座標を DAC 座標（0〜255）に変換する。

    - 縦横比を保ったまま、長い辺を 0〜255 に合わせる。短い辺は中央に寄せる
    - 画像は y が下向きが正だが、オシロは上向きが正なので、y を反転する
    """
    h, w = frame_shape
    scale = DAC_MAX / max(w - 1, h - 1, 1)
    off_x = (DAC_MAX - (w - 1) * scale) / 2
    off_y = (DAC_MAX - (h - 1) * scale) / 2

    out = []
    for c in contours:
        x = c[:, 0].astype(np.float64) * scale + off_x
        y = DAC_MAX - (c[:, 1].astype(np.float64) * scale + off_y)
        out.append(np.stack([x, y], axis=1))
    return out


def _rotate_closed(loop: np.ndarray, k: int) -> np.ndarray:
    """閉じた輪郭（最後の点 = 最初の点）を、k 番目の点から始まるように回す。"""
    core = loop[:-1]                      # 重複している最後の点を除く
    k = k % len(core)
    rotated = np.roll(core, -k, axis=0)   # k 番目が先頭になる
    return np.vstack([rotated, rotated[:1]])   # もう一度閉じる


def _order_and_join(loops: list[np.ndarray]) -> np.ndarray:
    """輪郭を、近い順に 1 本の折れ線につなぐ（最近傍法）。

    1. いちばん長い輪郭から始める
    2. 今いる位置から一番近い点を持つ輪郭を選ぶ
    3. その輪郭は閉じているので、一番近い点から回り始めて 1 周する
    4. 2〜3 を、全部の輪郭を使い切るまで繰り返す
    """
    remaining = list(loops)
    first = remaining.pop(int(np.argmax([_polyline_length(l) for l in remaining])))
    pieces = [first]
    pos = first[-1]

    while remaining:
        best_i, best_k, best_d = 0, 0, np.inf
        for i, loop in enumerate(remaining):
            d = np.hypot(loop[:, 0] - pos[0], loop[:, 1] - pos[1])
            k = int(np.argmin(d))
            if d[k] < best_d:
                best_i, best_k, best_d = i, k, float(d[k])
        loop = _rotate_closed(remaining.pop(best_i), best_k)
        pieces.append(loop)
        pos = loop[-1]

    return np.vstack(pieces)


def _resample(poly: np.ndarray, n: int) -> np.ndarray:
    """折れ線を、弧長が等間隔な n 点に取り直す。

    等間隔にすると、ビームの動く速さが一定になり、線の明るさが均一になる。
    """
    seg = np.hypot(np.diff(poly[:, 0]), np.diff(poly[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(seg)])    # 先頭からの道のり（累積の長さ）
    total = s[-1]
    if total == 0:                                  # 全部同じ点
        return np.repeat(poly[:1], n, axis=0)
    t = np.linspace(0.0, total, n)                  # 等間隔の道のり
    x = np.interp(t, s, poly[:, 0])                 # 道のり → x を線形補間
    y = np.interp(t, s, poly[:, 1])
    return np.stack([x, y], axis=1)


def contours_to_path(
    contours: list[np.ndarray],
    frame_shape: tuple[int, int],
    n_points: int,
) -> np.ndarray:
    """輪郭のリストを、N 点の経路にする。

    引数:
        contours: frame_to_contours の戻り値。各要素は (M, 2) float32、閉じた輪郭
        frame_shape: 元画像の (H, W)。座標変換に必要
        n_points: 出力する点数 N

    戻り値:
        (N, 2) uint8。1 行が [x, y]、値は 0〜255、y は上向きが正。
        輪郭が無いときは、画面中央の 1 点を N 回並べたものを返す。
    """
    if n_points < 2:
        raise ValueError("n_points は 2 以上にしてください")
    if not contours:
        return np.full((n_points, 2), DAC_CENTER, dtype=np.uint8)

    loops = _to_dac_space(contours, frame_shape)
    poly = _order_and_join(loops)
    pts = _resample(poly, n_points)
    return np.rint(np.clip(pts, 0, DAC_MAX)).astype(np.uint8)
