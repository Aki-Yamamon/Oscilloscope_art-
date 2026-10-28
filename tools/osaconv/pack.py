"""`.osa` ファイルの書き出しと読み込み。仕様は docs/FORMAT.md。

ヘッダ 16 バイト（リトルエンディアン）:
    magic "OSA1"(4) / version(1) / fps(1) / points_per_frame(2)
    / audio_rate(2) / audio_per_frame(2) / frame_count(4)
フレーム i:  x0,y0,x1,y1,...（各 u8、2N バイト） + 音声（u8 × audio_per_frame）

音声なしのときは audio_rate = 0、audio_per_frame = 0 にする（フレームは XY だけ）。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = b"OSA1"
VERSION = 1
HEADER_FORMAT = "<4sBBHHHI"                    # "<" = リトルエンディアン・詰め物なし
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)   # 16
AUDIO_SILENCE = 128


@dataclass(frozen=True)
class OsaHeader:
    fps: int
    points_per_frame: int
    audio_rate: int
    audio_per_frame: int
    frame_count: int

    @property
    def stride(self) -> int:
        """1 フレームのバイト数。"""
        return 2 * self.points_per_frame + self.audio_per_frame


class OsaWriter:
    """フレームを 1 枚ずつ追記して .osa を作る。

    使い方:
        with OsaWriter("out.osa", fps=30, points_per_frame=1000) as w:
            for xy in paths:          # xy は (N, 2) uint8
                w.write_frame(xy)

    総フレーム数は書き終わるまで分からないので、先に仮のヘッダを書き、
    終了時にファイルの先頭へ戻って正しいヘッダに書き直す。
    """

    def __init__(self, path, fps: int, points_per_frame: int,
                 audio_rate: int = 0, audio_per_frame: int = 0):
        self.path = Path(path)
        self.fps = fps
        self.n = points_per_frame
        self.audio_rate = audio_rate
        self.apf = audio_per_frame
        self.frame_count = 0
        self._f = None

    def _header_bytes(self) -> bytes:
        return struct.pack(HEADER_FORMAT, MAGIC, VERSION, self.fps, self.n,
                           self.audio_rate, self.apf, self.frame_count)

    def __enter__(self) -> "OsaWriter":
        self._f = open(self.path, "wb")
        self._f.write(self._header_bytes())        # 仮のヘッダ
        return self

    def write_frame(self, xy: np.ndarray, audio: np.ndarray | None = None) -> None:
        if xy.shape != (self.n, 2) or xy.dtype != np.uint8:
            raise ValueError(f"xy は ({self.n}, 2) の uint8 が必要です: {xy.shape}, {xy.dtype}")
        self._f.write(np.ascontiguousarray(xy).tobytes())    # x0,y0,x1,y1,... の順
        if self.apf > 0:
            if audio is None:
                audio = np.full(self.apf, AUDIO_SILENCE, dtype=np.uint8)
            if audio.shape != (self.apf,) or audio.dtype != np.uint8:
                raise ValueError(f"audio は ({self.apf},) の uint8 が必要です")
            self._f.write(audio.tobytes())
        self.frame_count += 1

    def __exit__(self, exc_type, exc, tb) -> None:
        self._f.seek(0)
        self._f.write(self._header_bytes())        # 正しいヘッダに書き直す
        self._f.close()


def read_osa(path) -> tuple[OsaHeader, np.ndarray, np.ndarray]:
    """.osa を読み込む。

    戻り値: (ヘッダ, xy, audio)
        xy:    shape (frame_count, N, 2)、uint8
        audio: shape (frame_count, audio_per_frame)、uint8（音声なしなら幅 0）
    """
    raw = Path(path).read_bytes()
    if len(raw) < HEADER_SIZE:
        raise ValueError("ファイルが短すぎます")
    magic, version, fps, n, a_rate, apf, frames = struct.unpack(HEADER_FORMAT, raw[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"magic が違います: {magic!r}")
    if version != VERSION:
        raise ValueError(f"未対応の version です: {version}")
    header = OsaHeader(fps, n, a_rate, apf, frames)

    expected = HEADER_SIZE + frames * header.stride
    if len(raw) != expected:
        raise ValueError(f"ファイルサイズが合いません: {len(raw)} (期待 {expected})")

    data = np.frombuffer(raw, dtype=np.uint8, offset=HEADER_SIZE).reshape(frames, header.stride)
    xy = data[:, : 2 * n].reshape(frames, n, 2)
    audio = data[:, 2 * n:]
    return header, xy, audio
