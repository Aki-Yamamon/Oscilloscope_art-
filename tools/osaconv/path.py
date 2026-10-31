"""輪郭(や折れ線)の集まりを、ESP32 に渡す「1 本の経路(N 点、値は 0〜255)」にする。

v3: _order / _is_closed / _sample_edges を高速化(結果は v2 と同じ)。
v2: つなぎ線(ジャンプ)を「補間しない」ようにした版。 tools/osaconv/path.py と差し替えて使う。
    contours_to_path(contours, frame_shape, n_points) のシグネチャは従来と同じ。

【旧版でつなぎ線が目立った理由】
    旧版は、輪郭どうしをつないだ 1 本の折れ線全体を「弧長が等間隔」に取り直していた。
    そのため、輪郭から輪郭へ飛ぶ区間にも、描く線と同じ密度で点が打たれた。
    アナログオシロの明るさは「ビームがそこに居た時間」で決まるので、
    ジャンプが描く線と同じ明るさになってしまう。

【この版の方針】
    1. 描く線(輪郭の中)だけを等間隔に打つ         → 描く線の明るさが均一
    2. ジャンプには点を 1 つも補間しない            → DAC が次の点へ一気に飛ぶだけ
       (ゼロ次ホールドの DAC なら、飛んでいる時間は点の保持時間より桁違いに短く、ほぼ見えない)
    3. 頂点は必ず点として残す                       → 四角形の角が丸まらない(テトリス向き)
    4. 点数はちょうど N にする(.osa の形式は変えない)  → ESP32 側の変更は不要

処理の流れ:
    polylines ─(_order)─> 近い順・向き調整 ─(_allocate)─> 辺ごとの点数 ─(_sample)─> (N, 2)
"""
from __future__ import annotations

import numpy as np

DAC_MAX = 255.0     # DAC の最大値(8bit)
DAC_CENTER = 128    # 輪郭が無いフレームでビームを置く位置
EPS = 1e-9


# ---------------------------------------------------------------- 基本ユーティリティ

def _seg_lengths(pts: np.ndarray) -> np.ndarray:
    return np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))


def _polyline_length(pts: np.ndarray) -> float:
    return float(_seg_lengths(pts).sum())


def _same_point(a, b) -> bool:
    """np.allclose(a, b) と同じ判定(atol=1e-8, rtol=1e-5)を、Python の float だけで行う。
    np.allclose は 1 回数十マイクロ秒かかり、毎フレーム何千回も呼ぶと支配的になる。"""
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    return abs(ax - bx) <= 1e-8 + 1e-5 * abs(bx) and abs(ay - by) <= 1e-8 + 1e-5 * abs(by)


def _is_closed(p: np.ndarray) -> bool:
    return len(p) > 2 and _same_point(p[0], p[-1])


def _clean(p: np.ndarray) -> np.ndarray | None:
    """連続する同じ点(長さ 0 の辺)を除く。閉じた輪郭は閉じたまま保つ。"""
    p = np.asarray(p, dtype=np.float64)
    closed = _is_closed(p)
    keep = np.r_[True, _seg_lengths(p) > EPS]
    p = p[keep]
    if closed and not _same_point(p[0], p[-1]):
        p = np.vstack([p, p[:1]])
    if len(p) < 2:
        return None
    return p


def _to_dac_space(contours: list[np.ndarray], frame_shape: tuple[int, int]) -> list[np.ndarray]:
    """ピクセル座標を DAC 座標(0〜255)に変換する。(旧版と同じ)

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


# ---------------------------------------------------------------- 描画順の決定(最近傍法)

def _rotate_closed(loop: np.ndarray, k: int) -> np.ndarray:
    """閉じた輪郭を、k 番目の点から始まるように回す。"""
    core = loop[:-1]
    k = k % len(core)
    rotated = np.roll(core, -k, axis=0)
    return np.vstack([rotated, rotated[:1]])


def _order(polys: list[np.ndarray]) -> list[np.ndarray]:
    """今いる位置に近いものから順に回る(最近傍法)。

    - 閉じた輪郭: いちばん近い頂点から回り始める(1 周して同じ点に戻る)
    - 開いた折れ線: 近い方の端から始める(向きは反転してよい)
      → 一筆書きの折れ線(オイラー路など)を渡せば、ジャンプなしで描ける

    v3: 結果は旧版と同じだが、「残りの全候補までの距離」を 1 ステップごとに numpy で一括計算する。
        旧版は候補ごとに Python ループと np.allclose を回していたので、本数 n の 2 乗に比例して遅かった。
    """
    n = len(polys)
    if n == 0:
        return []

    closed = np.array([_is_closed(p) for p in polys], dtype=bool)   # 判定は本数分の 1 回だけ
    first = int(np.argmax([_polyline_length(p) for p in polys]))
    alive = np.ones(n, dtype=bool)
    alive[first] = False
    out = [polys[first]]
    pos = polys[first][-1]

    c_idx = np.flatnonzero(closed)          # 閉じた輪郭: 全頂点を 1 つの配列にまとめる
    o_idx = np.flatnonzero(~closed)         # 開いた折れ線: 両端だけ見ればよい
    if len(c_idx):
        c_pts = np.vstack([polys[i] for i in c_idx])
        c_len = np.array([len(polys[i]) for i in c_idx])
        c_start = np.r_[0, np.cumsum(c_len)[:-1]]
    if len(o_idx):
        o_head = np.array([polys[i][0] for i in o_idx])
        o_tail = np.array([polys[i][-1] for i in o_idx])

    dist = np.empty(n)
    for _ in range(n - 1):
        dist.fill(np.inf)
        if len(c_idx):
            d = np.hypot(c_pts[:, 0] - pos[0], c_pts[:, 1] - pos[1])
            dist[c_idx] = np.minimum.reduceat(d, c_start)       # 輪郭ごとの「最も近い頂点」までの距離
        if len(o_idx):
            d0 = np.hypot(o_head[:, 0] - pos[0], o_head[:, 1] - pos[1])
            d1 = np.hypot(o_tail[:, 0] - pos[0], o_tail[:, 1] - pos[1])
            dist[o_idx] = np.minimum(d0, d1)
        dist[~alive] = np.inf
        i = int(np.argmin(dist))            # 同じ距離なら、番号の小さい方(旧版と同じ)
        alive[i] = False

        p = polys[i]
        if closed[i]:
            k = int(np.argmin(np.hypot(p[:, 0] - pos[0], p[:, 1] - pos[1])))
            p = _rotate_closed(p, k)
        elif float(np.hypot(*(p[0] - pos))) > float(np.hypot(*(p[-1] - pos))):
            p = p[::-1]
        out.append(p)
        pos = p[-1]
    return out


# ---------------------------------------------------------------- 点数の配分

def _allocate(weights: np.ndarray, total: int, minimum: int) -> np.ndarray:
    """total を weights の比率で整数に配る(最大剰余法)。各要素は minimum 以上、合計はちょうど total。"""
    w = np.asarray(weights, dtype=np.float64)
    m = len(w)
    if total < minimum * m:
        raise ValueError("total が足りません")
    fixed = np.zeros(m, dtype=bool)               # minimum に張り付いた要素
    while True:
        if fixed.all():
            ideal = np.full(m, float(minimum))
            break
        budget = total - minimum * int(fixed.sum())
        free = ~fixed
        ideal = np.full(m, float(minimum))
        wf = w[free]
        ideal[free] = (wf / wf.sum() * budget) if wf.sum() > 0 else budget / free.sum()
        newly = free & (ideal < minimum)
        if not newly.any():
            break
        fixed |= newly
    base = np.floor(ideal + 1e-12).astype(int)
    left = total - int(base.sum())
    if left > 0:
        order = np.argsort(-(ideal - base), kind="stable")
        base[order[:left]] += 1
    return base


# ---------------------------------------------------------------- サンプリング

def _sample_edges(p: np.ndarray, ks: np.ndarray) -> np.ndarray:
    """辺 e に ks[e] 点を等間隔に置く(辺の終点を含み、始点は含まない)。先頭に始点を 1 つ足す。

    頂点は必ず点になるので、角が丸まらない。(v3: 辺ごとのループなしで、一括で計算する)
    """
    ks = np.asarray(ks, dtype=np.int64)
    a = np.repeat(p[:-1], ks, axis=0)
    b = np.repeat(p[1:], ks, axis=0)
    starts = np.cumsum(ks) - ks
    j = np.arange(int(ks.sum())) - np.repeat(starts, ks) + 1      # 辺の中での通し番号 1..k
    t = (j / np.repeat(ks, ks))[:, None]
    return np.vstack([p[:1], a + (b - a) * t])


def _sample_arclength(p: np.ndarray, m: int) -> np.ndarray:
    """折れ線を、弧長が等間隔な m+1 点に取り直す(頂点は保証されない。点が足りないときの予備)。"""
    seg = _seg_lengths(p)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], m + 1)
    return np.stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])], axis=1)


# ---------------------------------------------------------------- 重なった辺の整理

def merge_polylines(polys: list[np.ndarray], tol: float = 1e-3) -> list[np.ndarray]:
    """重なって描かれる辺を 1 本にし、つながる辺を、なるべく長い折れ線にまとめる。

    隣り合うブロックが共有する辺(同じ線を 2 回描く無駄)をなくすので、線の総延長が減る。
    1 フレームの点数 N は固定なので、総延長が減るほど、線 1 本あたりの点が増え、数珠つなぎになりにくい。
    つなぎ直すことで、折れ線の本数(= ジャンプの回数)も減る。

    - 見た目は変わらない(描く辺の集合は同じ)。頂点の位置も変えない
    - 座標は tol の精度で「同じ点」とみなす
    - 辺の途中で重なるだけの線(長い辺と、その一部にあたる短い辺)は、まとめられない
    """
    inv = 1.0 / tol
    vid: dict[tuple[int, int], int] = {}
    coords: list[tuple[float, float]] = []
    adj: list[list[tuple[int, int]]] = []
    edges: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    for p in polys:
        prev = -1
        for x, y in np.asarray(p, dtype=np.float64).tolist():
            key = (round(x * inv), round(y * inv))
            v = vid.get(key)
            if v is None:
                v = len(coords)
                vid[key] = v
                coords.append((x, y))
                adj.append([])
            if prev >= 0 and v != prev:
                ek = (prev, v) if prev < v else (v, prev)
                if ek not in seen:
                    seen.add(ek)
                    e = len(edges)
                    edges.append(ek)
                    adj[prev].append((v, e))
                    adj[v].append((prev, e))
            prev = v

    used = [False] * len(edges)
    ptr = [0] * len(coords)

    def next_edge(v: int):
        a = adj[v]
        i = ptr[v]
        while i < len(a) and used[a[i][1]]:
            i += 1
        ptr[v] = i
        return a[i] if i < len(a) else None

    # 次数が奇数の頂点から始めると、少ない本数で全部の辺をたどれる
    starts = [v for v in range(len(coords)) if len(adj[v]) % 2 == 1] + list(range(len(coords)))
    strokes: list[np.ndarray] = []
    for s in starts:
        while True:
            ne = next_edge(s)
            if ne is None:
                break
            path = [s]
            while ne is not None:
                w, e = ne
                used[e] = True
                path.append(w)
                ne = next_edge(w)
            strokes.append(np.array([coords[i] for i in path], dtype=np.float64))
    return strokes


def polylines_to_path(
    polylines: list[np.ndarray],
    n_points: int,
    return_jumps: bool = False,
    merge: bool = False,
):
    """DAC 座標(0〜255)の折れ線のリストを、ちょうど n_points 点の経路にする。

    polylines: 各要素は (M, 2)。最後の点 = 最初の点 なら閉じた輪郭、そうでなければ開いた折れ線。
    戻り値: (N, 2) float64。return_jumps=True なら、ジャンプ先の点の番号の配列も返す。

    ジャンプ(折れ線から次の折れ線への移動)には点を補間しない。
    merge=True なら、先に merge_polylines で重なった辺を整理する(ゲーム画面など、辺を共有する図形向け)。
    """
    if n_points < 2:
        raise ValueError("n_points は 2 以上にしてください")

    polys = [q for q in (_clean(p) for p in polylines) if q is not None]
    if merge and polys:
        polys = merge_polylines(polys)

    if not polys:
        pts = np.full((n_points, 2), float(DAC_CENTER))
        return (pts, np.array([], dtype=int)) if return_jumps else pts

    polys = _order(polys)

    # 点が足りないときは、短い折れ線から捨てる(最小でも、1 本あたり 始点 + 1 辺 = 2 点が要る)
    # v3: 捨てる必要があるときだけ並べ直す(旧版は毎回 _order を 2 回呼んでいた)
    if 2 * len(polys) > n_points:
        polys.sort(key=_polyline_length, reverse=True)
        while len(polys) > 1 and 2 * len(polys) > n_points:
            polys.pop()
        polys = _order(polys)

    n_poly = len(polys)
    n_edges = sum(len(p) - 1 for p in polys)
    budget = n_points - n_poly                    # 各折れ線の始点 1 点ずつを除いた、辺に使える点数

    if budget >= n_edges:
        # 全部の辺に最低 1 点(= 頂点)を置ける: 辺の長さに比例して配る
        lens = np.concatenate([_seg_lengths(p) for p in polys])
        ks = _allocate(lens, budget, minimum=1)
        chunks, i = [], 0
        for p in polys:
            e = len(p) - 1
            chunks.append(_sample_edges(p, ks[i:i + e]))
            i += e
    else:
        # 頂点が多すぎる(動画の複雑な輪郭など): 折れ線ごとに弧長で取り直す
        lens = np.array([_polyline_length(p) for p in polys])
        ms = _allocate(lens, budget, minimum=1)
        chunks = [_sample_arclength(p, int(m)) for p, m in zip(polys, ms)]

    pts = np.vstack(chunks)
    assert len(pts) == n_points, (len(pts), n_points)

    if return_jumps:
        starts = np.cumsum([0] + [len(c) for c in chunks[:-1]])[1:]
        return pts, starts.astype(int)
    return pts


def contours_to_path(
    contours: list[np.ndarray],
    frame_shape: tuple[int, int],
    n_points: int,
) -> np.ndarray:
    """輪郭のリストを、N 点の経路(uint8)にする。(従来と同じシグネチャ)

    戻り値: (N, 2) uint8。1 行が [x, y]、値は 0〜255、y は上向きが正。
    輪郭が無いときは、画面中央の 1 点を N 回並べたものを返す。
    """
    if n_points < 2:
        raise ValueError("n_points は 2 以上にしてください")
    if not contours:
        return np.full((n_points, 2), DAC_CENTER, dtype=np.uint8)
    pts = polylines_to_path(_to_dac_space(contours, frame_shape), n_points)
    return np.rint(np.clip(pts, 0, DAC_MAX)).astype(np.uint8)
