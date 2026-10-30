"""画面(Screen)の定義。画面は「キー入力を受け取り、1 フレーム(N 点)を返す」だけのもの。

キーは文字列で受け取る:  "up" "down" "enter" "esc" "backspace" と、文字入力 "char"(ch に文字)。
(pygame のキーコードへの変換は app.py の担当。ここは pygame に依存しない)

画面を足すには Screen を継承して、app.py の build_app() で register する。
テトリスは、ここに TetrisScreen を足してメニューの "TETRIS" から goto する想定。
"""
from __future__ import annotations

import numpy as np
import wave
from pathlib import Path

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


class HomePreviewScreen(Screen):
    """メニューの HOME。home.osa だけを表示する(文字は出さない)。Enter か Esc でメニューへ戻る。"""

    def __init__(self, home: HomeScreen, back: str = "menu"):
        self.home, self.back = home, back

    def on_enter(self, app) -> None:
        self.home.on_enter(app)                    # home.osa を頭から

    def handle(self, app, key, ch=None) -> None:
        if key in ("enter", "esc"):
            app.goto(self.back)

    def frame(self, app, dt: float) -> np.ndarray:
        return self.home.frame(app, dt)


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
    def __init__(self, menu: Menu, back: str = "home"):
        self.menu = menu
        self.back = back                 # Esc で戻る画面の名前

    def handle(self, app, key, ch=None) -> None:
        if key == "up":
            self.menu.move(-1)
        elif key == "down":
            self.menu.move(1)
        elif key == "enter":
            self.menu.select()
        elif key == "esc":
            app.goto(self.back)          # ← 以前は app.goto("home") だった

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

# ------------------------------------------------------------------ BADAPPLE のあとの演出

def _wav_seconds(path, default: float = 15.0) -> float:
    """wav の長さ(秒)。読めなければ default。"""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return default


def _centered_lines(lines, size: float, gap: float = 14.0) -> list:
    """複数行の文字を、画面の中央にそろえて並べた折れ線にする。"""
    total = len(lines) * size + (len(lines) - 1) * gap
    top = 127.5 + total / 2
    polys: list = []
    for i, line in enumerate(lines):
        polys += text_to_polylines(line, center_x(line, size), top - size - i * (size + gap), size)
    return polys


class OutroScreen(Screen):
    """BADAPPLE を最後まで再生したあとの一連の動作。

        phase 0: THANK YOU / WATCHING を表示
        phase 1: NOW ENJOY / THE NYANCAT を表示 + 同時に nyancat.wav を開始
        phase 2: home.osa を再生(音楽が終わるまで)
        音楽が終わったら end_screen("home")へ。Esc で、音楽を止めてメニューへ。
    """
    THANKS_LINES = ("THANK YOU", "WATCHING")
    NYAN_LINES = ("NOW ENJOY", "THE NYANCAT..")
    THANKS_SEC = 3.0        # phase 0 の長さ
    ENTER_AFTER_SEC = 5.0   # NOW ENJOY の表示から、この秒数がたつと Enter でメニューへ行ける
    NYAN_TEXT_SEC = 3.0     # phase 1 の長さ(音楽はこの先頭から鳴り続ける)

    def __init__(self, home: HomeScreen, wav_path, end_screen: str = "home"):
        self.home, self.wav, self.end_screen = home, Path(wav_path), end_screen
        self.music_sec = _wav_seconds(self.wav)        # 15 秒ほど。wav の長さから自動で測る
        self.t = 0.0
        self.music_t = 0.0
        self.phase = 0

    def on_enter(self, app) -> None:
        self.t, self.music_t, self.phase = 0.0, 0.0, 0

    def handle(self, app, key, ch=None) -> None:
        if key == "esc":
            app.audio.stop()
            app.goto("menu")
        elif key == "enter" and self.phase >= 1 and self.music_t >= self.ENTER_AFTER_SEC:
            app.audio.stop()                           # NOW ENJOY の表示から 5 秒たったら、Enter でメニューへ
            app.goto("menu")

    def frame(self, app, dt: float) -> np.ndarray:
        self.t += dt
        if self.phase == 0 and self.t >= self.THANKS_SEC:
            self.phase, self.t = 1, 0.0
            if self.wav.is_file():
                app.audio.play(self.wav)               # 文字の表示と同時に、音楽を開始
            else:
                print(f"[ERROR] ファイルがありません: {self.wav}")
        elif self.phase == 1 and self.t >= self.NYAN_TEXT_SEC:
            self.phase = 2
            self.home.on_enter(app)                    # home.osa を頭から

        if self.phase >= 1:
            self.music_t += dt
            if self.music_t >= self.music_sec:         # 音楽が終わった
                app.audio.stop()
                app.goto(self.end_screen)
                return app.current.frame(app, 0.0)

        if self.phase == 0:
            return app.render(_centered_lines(self.THANKS_LINES, 22))
        if self.phase == 1:
            return app.render(_centered_lines(self.NYAN_LINES, 20))
        return self.home.frame(app, dt)