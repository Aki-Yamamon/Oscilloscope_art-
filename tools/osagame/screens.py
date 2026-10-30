"""画面(Screen)の定義。画面は「キー入力を受け取り、1 フレーム(N 点)を返す」だけのもの。

キーは文字列で受け取る:  "up" "down" "enter" "esc" "backspace" と、文字入力 "char"(ch に文字)。
(pygame のキーコードへの変換は app.py の担当。ここは pygame に依存しない)

画面を足すには Screen を継承して、app.py の build_app() で register する。
テトリスは、ここに TetrisScreen を足してメニューの "TETRIS" から goto する想定。
"""
from __future__ import annotations

import numpy as np

from osagame.ui import Menu, TextBox, center_x, text_to_polylines
from osaconv.pack import read_osa


class Screen:
    def on_enter(self, app) -> None:
        pass

    def handle(self, app, key: str, ch: str | None = None) -> None:
        pass

    def polylines(self, app, dt: float) -> list:
        return []

    def frame(self, app, dt: float) -> np.ndarray:
        """(N, 2) uint8 を返す。"""
        return app.render(self.polylines(app, dt))


class HomeScreen(Screen):
    """ホーム画面。.osa(GIF などを変換した短い映像)をループ再生する。Enter でメニューへ。

    .osa が無いときは、文字だけのタイトル画面になる(動画なしでも動作確認できる)。
    """

    def __init__(self, osa_path: str | None, n_points: int):
        self.xy = None
        self.fps = 30
        self.t = 0.0
        if osa_path:
            header, xy, _ = read_osa(osa_path)
            if header.points_per_frame != n_points:
                raise SystemExit(
                    f"{osa_path} の点数は {header.points_per_frame} ですが、--points は {n_points} です。"
                    f"変換時の --points を合わせてください。")
            self.xy, self.fps = xy, header.fps

    def on_enter(self, app) -> None:
        self.t = 0.0

    def handle(self, app, key, ch=None) -> None:
        if key == "enter":
            app.goto("menu")
        elif key == "esc":
            app.running = False

    def frame(self, app, dt: float) -> np.ndarray:
        self.t += dt
        if self.xy is not None:
            return self.xy[int(self.t * self.fps) % len(self.xy)]
        polys = text_to_polylines("OSCILO", center_x("OSCILO", 36), 140, 36)
        if int(self.t * 1.5) % 2 == 0:                         # 点滅
            polys += text_to_polylines("PRESS ENTER", center_x("PRESS ENTER", 12), 70, 12)
        return app.render(polys)


class MenuScreen(Screen):
    def __init__(self, menu: Menu):
        self.menu = menu

    def handle(self, app, key, ch=None) -> None:
        if key == "up":
            self.menu.move(-1)
        elif key == "down":
            self.menu.move(1)
        elif key == "enter":
            self.menu.select()
        elif key == "esc":
            app.goto("home")

    def polylines(self, app, dt: float) -> list:
        self.menu.update(dt)
        return self.menu.polylines()


class MessageScreen(Screen):
    """メッセージウィンドウ 1 枚。Enter で、表示を最後まで進める → もう一度で戻る。"""

    def __init__(self, text: str, back: str = "menu"):
        self.text, self.back = text, back
        self.box = TextBox(16, 90, 224, 80, text, size=11)

    def on_enter(self, app) -> None:
        self.box.set_text(self.text)

    def handle(self, app, key, ch=None) -> None:
        if key == "enter":
            if self.box.done:
                app.goto(self.back)
            else:
                self.box.skip()
        elif key == "esc":
            app.goto(self.back)

    def polylines(self, app, dt: float) -> list:
        self.box.update(dt)
        return self.box.polylines()


class TextBoxDemoScreen(Screen):
    """テキストボックスの使い方の見本: メッセージ → 名前の入力 → あいさつ → メニューへ戻る。"""

    def __init__(self):
        self.step = 0
        self.name = ""
        self.msg = TextBox(16, 16, 224, 84, size=11)
        self.inp = TextBox(16, 120, 224, 40, input_mode=True, size=14, max_len=12)

    def on_enter(self, app) -> None:
        self.step = 0
        self.inp.set_text("", typewriter=False)
        self.msg.set_text("HELLO! WHAT IS YOUR NAME?")

    def handle(self, app, key, ch=None) -> None:
        if key == "esc":
            app.goto("menu")
        elif self.step == 0:                       # メッセージを読む
            if key == "enter":
                if self.msg.done:
                    self.step = 1
                    self.msg.set_text("TYPE YOUR NAME AND PRESS ENTER.")
                else:
                    self.msg.skip()
        elif self.step == 1:                       # 名前を入力する
            if key == "char" and ch:
                self.inp.append(ch)
            elif key == "backspace":
                self.inp.backspace()
            elif key == "enter" and self.inp.text:
                self.name = self.inp.text
                self.step = 2
                self.msg.set_text(f"NICE TO MEET YOU, {self.name}!")
        else:                                      # あいさつ → 戻る
            if key == "enter":
                if self.msg.done:
                    app.goto("menu")
                else:
                    self.msg.skip()

    def polylines(self, app, dt: float) -> list:
        self.msg.update(dt)
        self.inp.update(dt)
        polys = self.msg.polylines()
        if self.step == 1:
            polys += self.inp.polylines()
        return polys
