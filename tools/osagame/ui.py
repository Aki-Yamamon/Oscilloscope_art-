"""文字・メニュー・テキストボックス。出力はすべて「折れ線のリスト」(DAC 座標 0〜255、y は上向きが正)。

折れ線は osaconv.path.polylines_to_path に渡すと、ちょうど N 点の経路になる。
このモジュールは pygame にも ESP32 にも依存しない(単体でテストできる)。
"""
from __future__ import annotations

import math

import numpy as np

from osagame.font import ADVANCE, CELL_H, CELL_W, GLYPHS

SCREEN = 255.0   # 画面の一辺(DAC 座標)


# ------------------------------------------------------------------ 文字

def advance(size: float) -> float:
    """次の文字までの送り(DAC 単位)。size は文字の高さ。"""
    return ADVANCE * size / CELL_H


def text_width(text: str, size: float) -> float:
    if not text:
        return 0.0
    return (len(text) - 1) * advance(size) + CELL_W * size / CELL_H


def center_x(text: str, size: float) -> float:
    return (SCREEN - text_width(text, size)) / 2


def text_to_polylines(text: str, x: float, y: float, size: float) -> list[np.ndarray]:
    """文字列を折れ線にする。(x, y) は 1 文字目の左下。size は文字の高さ(DAC 単位)。"""
    s = size / CELL_H
    out: list[np.ndarray] = []
    for i, ch in enumerate(text):
        glyph = GLYPHS.get(ch.upper(), GLYPHS["?"])
        ox = x + i * ADVANCE * s
        for stroke in glyph:
            out.append(np.array([(ox + px * s, y + py * s) for px, py in stroke], dtype=np.float64))
    return out


def rect_polyline(x: float, y: float, w: float, h: float) -> np.ndarray:
    """閉じた四角形(左下 (x, y)、幅 w、高さ h)。"""
    return np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], dtype=np.float64)


def wrap_text(text: str, cols: int) -> list[str]:
    """単語単位で折り返す。長すぎる単語は強制的に割る。\\n は改行。"""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split(" "):
            while len(w) > cols:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:cols])
                w = w[cols:]
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= cols:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


# ------------------------------------------------------------------ テキストボックス

class TextBox:
    """枠つきのテキストボックス。RPG のメッセージウィンドウ風(1 文字ずつ表示)にも、
    キーボード入力欄(input_mode=True)にも使える。"""

    def __init__(self, x, y, w, h, text="", size=10.0, pad=7.0, cps=16.0,
                 line_gap=0.7, input_mode=False, max_len=40):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.size, self.pad, self.cps, self.line_gap = size, pad, cps, line_gap
        self.input_mode = input_mode
        self.max_len = max_len
        self.text = ""
        self._shown = 0.0
        self._t = 0.0
        self.set_text(text, typewriter=not input_mode)

    # ---- 内容の操作
    def set_text(self, text: str, typewriter: bool = True) -> None:
        self.text = text
        self._shown = 0.0 if typewriter else float(len(text))

    def append(self, ch: str) -> None:
        if len(self.text) < self.max_len and ch.isprintable():
            self.text += ch
            self._shown = float(len(self.text))

    def backspace(self) -> None:
        self.text = self.text[:-1]
        self._shown = float(len(self.text))

    def skip(self) -> None:
        """表示を一気に最後まで進める。"""
        self._shown = float(len(self.text))

    @property
    def done(self) -> bool:
        return self._shown >= len(self.text)

    def update(self, dt: float) -> None:
        self._t += dt
        if self._shown < len(self.text):
            self._shown = min(float(len(self.text)), self._shown + self.cps * dt)

    # ---- 描画
    def polylines(self) -> list[np.ndarray]:
        s = self.size / CELL_H
        adv = ADVANCE * s
        inner_w = self.w - 2 * self.pad
        cols = max(1, int((inner_w + (ADVANCE - CELL_W) * s) // adv))
        line_h = self.size * (1 + self.line_gap)
        rows = max(1, int((self.h - 2 * self.pad + self.size * self.line_gap) // line_h))

        full = self.text
        cursor_on = self.input_mode and (int(self._t * 2) % 2 == 0)
        if cursor_on:
            full += "_"
        lines = wrap_text(full, cols)

        # 1 文字ずつ表示: 見えている文字数だけ行から切り出す
        remaining = int(self._shown) if not self.input_mode else 10 ** 9
        shown_lines: list[str] = []
        for ln in lines:
            if remaining <= 0:
                break
            shown_lines.append(ln[:remaining])
            remaining -= len(ln)
        shown_lines = shown_lines[-rows:]       # はみ出したら、最後の rows 行だけ見せる

        polys = [rect_polyline(self.x, self.y, self.w, self.h)]
        top = self.y + self.h - self.pad - self.size
        for i, ln in enumerate(shown_lines):
            polys += text_to_polylines(ln, self.x + self.pad, top - i * line_h, self.size)
        return polys


# ------------------------------------------------------------------ メニュー

class Menu:
    """RPG 風のメニュー。選択中の項目の左に ">" が出る。上下で移動、決定で callback を実行。"""

    def __init__(self, items, title="MENU", title_size=18.0, item_size=14.0,
                 title_y=228.0, top=170.0, step=30.0, cursor_x=22.0, label_x=48.0):
        self.items = list(items)            # [(ラベル, 引数なしの関数), ...]
        self.title = title
        self.title_size, self.item_size = title_size, item_size
        self.title_y, self.top, self.step = title_y, top, step
        self.cursor_x, self.label_x = cursor_x, label_x
        self.index = 0
        self._t = 0.0

    def move(self, d: int) -> None:
        self.index = (self.index + d) % len(self.items)

    def select(self):
        return self.items[self.index][1]()

    def update(self, dt: float) -> None:
        self._t += dt

    def polylines(self) -> list[np.ndarray]:
        polys: list[np.ndarray] = []
        if self.title:
            polys += text_to_polylines(self.title, center_x(self.title, self.title_size),
                                       self.title_y, self.title_size)
            polys.append(np.array([(self.cursor_x, self.title_y - 10), (SCREEN - self.cursor_x, self.title_y - 10)]))
        for i, (label, _) in enumerate(self.items):
            y = self.top - i * self.step
            polys += text_to_polylines(label, self.label_x, y, self.item_size)
            if i == self.index:
                bob = 2.5 * (0.5 + 0.5 * math.sin(self._t * 2 * math.pi * 1.5))   # カーソルが左右に小さく揺れる
                polys += text_to_polylines(">", self.cursor_x + bob, y, self.item_size)
        return polys
