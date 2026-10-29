"""動画 → .osa の変換（全体をつなぐ部分）。

    python -m osaconv badapple.mp4 -o out.osa --seconds 30

流れ（フレームごと）:
    動画 ─(cv2)→ グレースケール ─(contour.py)→ 輪郭 ─(path.py)→ N 点の経路 ─(pack.py)→ .osa
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from osaconv.contour import ContourParams, frame_to_contours
from osaconv.pack import OsaWriter
from osaconv.path import contours_to_path


def convert_video(
    video_path,
    out_path,
    fps: int = 30,
    n_points: int = 1000,
    start_sec: float = 0.0,
    seconds: float | None = None,
    params: ContourParams | None = None,
    progress: bool = True,
) -> dict:
    """動画を .osa に変換する。統計（辞書）を返す。"""
    if not Path(video_path).exists():
        raise FileNotFoundError(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"動画を開けませんでした: {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or float(fps)
    start_idx = int(round(start_sec * src_fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_idx)
    cur = start_idx                                   # 次に読むフレームの番号
    total_out = int(seconds * fps) if seconds is not None else None

    n_contours_list: list[int] = []
    last_path = None
    last_idx = -1
    i = 0
    with OsaWriter(out_path, fps=fps, points_per_frame=n_points) as writer:
        while total_out is None or i < total_out:
            # 出力フレーム i に対応する、元動画のフレーム番号（fps が違っても時間が合うようにする）
            target = start_idx + int(round(i * src_fps / fps))
            if target != last_idx:
                ended = False
                while cur < target:                   # 使わないフレームを読み飛ばす
                    if not cap.grab():
                        ended = True
                        break
                    cur += 1
                if ended:
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                cur += 1
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                contours = frame_to_contours(gray, params)
                last_path = contours_to_path(contours, gray.shape, n_points)
                n_contours_list.append(len(contours))
                last_idx = target
            assert last_path is not None   # 最初の周回で必ず作られる（last_idx の初期値が -1 のため）
            writer.write_frame(last_path)
            i += 1
            if progress and i % 30 == 0:
                print(f"  {i} frames ({i / fps:.1f} s)")
    cap.release()

    return {
        "frames": i,
        "seconds": i / fps,
        "mean_contours": sum(n_contours_list) / max(len(n_contours_list), 1),
        "max_contours": max(n_contours_list, default=0),
        "empty_frames": sum(1 for c in n_contours_list if c == 0),
        "file_bytes": Path(out_path).stat().st_size,
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="動画を .osa に変換する")
    ap.add_argument("video")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--points", type=int, default=1000, help="1 フレームの点数 N")
    ap.add_argument("--start", type=float, default=0.0, help="開始位置（秒）")
    ap.add_argument("--seconds", type=float, default=None, help="変換する長さ（秒）。省略で最後まで")
    ap.add_argument("--threshold", type=int, default=None, help="省略で大津法")
    ap.add_argument("--invert", action="store_true", help="白黒を反転")
    ap.add_argument("--blur", type=int, default=0, help="ぼかし（奇数。0 でなし）")
    ap.add_argument("--epsilon", type=float, default=1.0)
    ap.add_argument("--min-length", type=float, default=20.0)
    ap.add_argument("--external", action="store_true", help="外側の輪郭だけ使う")
    args = ap.parse_args(argv)

    params = ContourParams(
        threshold=args.threshold, invert=args.invert, blur_ksize=args.blur,
        epsilon=args.epsilon, min_length=args.min_length,
        retrieval=cv2.RETR_EXTERNAL if args.external else cv2.RETR_LIST,
    )
    print(params)
    stats = convert_video(args.video, args.out, fps=args.fps, n_points=args.points,
                          start_sec=args.start, seconds=args.seconds, params=params)
    print("done:", stats)
    print(f"  {stats['file_bytes'] / 1e6:.2f} MB / {stats['seconds']:.1f} s")
