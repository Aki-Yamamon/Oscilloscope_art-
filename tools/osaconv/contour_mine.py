from dataclasses import dataclass
import cv2
import numpy


@dataclass
class ContourParams:
    threshold: int | None = None   # None なら大津法
    invert: bool = False           # 白黒を反転するか
    blur_ksize: int = 0            # 0 ならぼかさない（奇数のみ）
    epsilon: float = 1.0           # 輪郭の簡略化の強さ（ピクセル）
    min_length: float = 20.0       # これ未満の輪郭は捨てる（ピクセル）
    retrieval: int = cv2.RETR_LIST # 輪郭の取り方