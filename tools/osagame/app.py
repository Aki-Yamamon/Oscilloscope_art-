"""ホーム / メニュー / テキストボックスのアプリ本体。PC のキーボードで操作して、ESP32 に XY フレームを送る。

    python -m osagame --port COM6 --baud 921600 --home home.osa
    python -m osagame --no-serial                  # ESP32 なしで、PC 画面のプレビューだけ動かす

操作: ↑↓ = カーソル移動 / Enter = 決定 / Esc = 戻る / 文字キー = テキスト入力
(キーを受け取るのは、開いた小さなウィンドウ。そのウィンドウをクリックして選択しておくこと)

通信は osaconv/stream.py のパケット(type 0x01 = XY フレーム)をそのまま使う。ESP32 側の変更は不要。
静止画面でも毎フレーム送り続ける(ESP32 は 1 秒以上途切れると、動く円に戻るため)。
"""
from __future__ import annotations

import argparse
import threading

import numpy as np

from osaconv.path import DAC_CENTER, DAC_MAX, polylines_to_path
from osagame.screens import (HomePreviewScreen, HomeScreen, MenuScreen, MessageScreen, OutroScreen, TextBoxDemoScreen)
from osagame.ui import Menu

import subprocess
import sys
from pathlib import Path
import time, tracemalloc
import cProfile, pstats, io

TOOLS_DIR = Path(__file__).resolve().parents[1]       # tools/
SOURCE_DIR = TOOLS_DIR / "source"                      # home.osa / badapple.osa / badapple.wav の置き場所
HOME_OSA = SOURCE_DIR / "home.osa"
BADAPPLE_OSA = SOURCE_DIR / "badapple.osa"
BADAPPLE_WAV = SOURCE_DIR / "badapple.wav"

NYANCAT_OSA = SOURCE_DIR / "nyancat.osa"
NYANCAT_WAV = SOURCE_DIR / "nyancat.wav"
RINK_OSA = SOURCE_DIR / "enter_the_rink.osa"
RINK_WAV = SOURCE_DIR / "enter_the_rink.wav"


class NullAudio:
    """音声なし(pygame が無いテスト用)。"""
    def play(self, path, loops=-1) -> None:
        print(f"[audio] play {path} (loops={loops})")
        
    def play_se(self, path) -> None:
        print(f"[audio] play_se {path}")

    def stop(self) -> None:
        pass


class PygameAudio:
    """pygame.mixer での再生。最初に鳴らすときに初期化する(BADAPPLE 再生中は、音声デバイスに触れない)。"""
    def __init__(self, pg):
        self.pg = pg
        self.ok = None
        self.sounds = {}  # 効果音をキャッシュする辞書

    def _init(self) -> bool:
        if self.ok is None:
            try:
                self.pg.mixer.init()
                self.pg.mixer.set_num_channels(8) # 同時に複数のSEを鳴らせるようにチャンネルを増やす
                self.ok = True
            except self.pg.error as e:
                print("[osagame] 音声を初期化できません:", e)
                self.ok = False
        return self.ok

    def play(self, path, loops=-1) -> None:
        """BGMの再生(music)"""
        if self._init():
            self.pg.mixer.music.load(str(path))
            self.pg.mixer.music.play(loops)
            
    def play_se(self, path) -> None:
        """効果音の再生(Sound)"""
        if self._init():
            sp = str(path)
            if sp not in self.sounds:
                try:
                    self.sounds[sp] = self.pg.mixer.Sound(sp)
                except Exception as e:
                    print(f"[osagame] SE load error: {e}")
                    return
            self.sounds[sp].play()

    def stop(self) -> None:
        if self.ok:
            self.pg.mixer.music.stop()

class App:
    def __init__(self, n_points: int):
        self.n = n_points
        self.running = True
        self.launch = None           # 外部プレーヤーの起動依頼: (osa, wav)。main() のループが拾って実行する
        self.audio = NullAudio()     # main() が PygameAudio に差し替える
        self.screens: dict = {}
        self.current = None
        # app.py: App.__init__ の中に追加
        self.game_points = n_points


    def register(self, name: str, screen) -> None:
        self.screens[name] = screen

    def goto(self, name: str) -> None:
        self.current = self.screens[name]
        self.current.on_enter(self)

    def play_video(self, osa: Path, wav: Path, after: str | None = None) -> None:
        """動画の再生を依頼する。ファイルを確かめて、main() のループに渡す(実行は main() のループ)。
        after: 最後まで再生したあとに移る画面の名前。None なら、今の画面のまま。"""
        missing = [p for p in (osa, wav) if not p.is_file()]
        if missing:
            for p in missing:
                print(f"[ERROR] ファイルがありません: {p}")
            return                   # メニューに留まる
        self.launch = (osa, wav, after)

    # def render(self, polys: list) -> np.ndarray:
    #     """折れ線のリスト → (N, 2) uint8。何も無ければ中央に 1 点。"""
    #     if not polys:
    #         return np.full((self.n, 2), DAC_CENTER, dtype=np.uint8)
    #     pts = polylines_to_path(polys, self.n)
    #     return np.rint(np.clip(pts, 0, DAC_MAX)).astype(np.uint8)

    # app.py: App.render を置き換え(merge=True は前回の変更)
    def render(self, polys: list, n: int | None = None) -> np.ndarray:
        n = n or self.n
        if not polys:
            return np.full((n, 2), DAC_CENTER, dtype=np.uint8)
        pts = polylines_to_path(polys, n, merge=True)
        return np.rint(np.clip(pts, 0, DAC_MAX)).astype(np.uint8)


def build_app(n_points: int, home_osa: str | None) -> App:
    app = App(n_points)

    # ---- メニュー(上の階層から順に)
    video_menu = Menu([
        ("BAD APPLE!!",       lambda: app.play_video(BADAPPLE_OSA, BADAPPLE_WAV, after="outro")),
        ("ENTER THE RINK", lambda: app.goto("addvideo")),          # YouTube の ID を入力して再生
        ("HISTORY",        lambda: app.goto("addvideo_history")),  # 再生した動画の一覧
        ("BACK",           lambda: app.goto("menu")),
    ], title="VIDEO")
    
    def open_lb(game_name):
        app.screens["leaderboard"].setup(game_name)
        app.goto("leaderboard")

    lb_menu = Menu([
        ("PAC MAN", lambda: open_lb("pacman")),
        ("TETRIS",  lambda: open_lb("tetris")),
        ("BACK",    lambda: app.goto("game")),
    ], title="LEADERBOARD")

    game_menu = Menu([
        ("TETRIS",         lambda: app.goto("tetris")),
        ("PAC MAN",        lambda: app.goto("pacman")),
        ("LEADERBOARD",    lambda: app.goto("leaderboard_menu")),
        ("BACK",           lambda: app.goto("menu")),
    ], title="GAME")

    def open_sub(name: str, sub: Menu):
        def _open():
            sub.index = 0                # 入り直したときは、カーソルを先頭に戻す
            app.goto(name)
        return _open

    main_menu = Menu([
        ("VIDEO",          open_sub("video", video_menu)),
        ("GAME",           open_sub("game", game_menu)),
        ("EXPLINE",        lambda: app.goto("expline")),
        ("HOME",           lambda: app.goto("homeview")),
    ]) 
    home = HomeScreen(home_osa, n_points)
    nyan = HomeScreen(str(NYANCAT_OSA), n_points)            # BADAPPLE のあとに流す動画(nyancat.osa)
    app.register("home", home)
    app.register("homeview", HomePreviewScreen(home))        # メニューの HOME: home.osa だけを表示
    app.register("outro", OutroScreen(nyan, NYANCAT_WAV))    # BADAPPLE が最後まで再生されたあとの演出

    from osagame.osatetris.tetris_screen import TetrisScreen
    from osagame.osapacman.pacman_screen import PacmanScreen
    from osagame.history import NameEntryScreen, LeaderboardScreen # 追加
    
    app.register("menu", MenuScreen(main_menu, back="home"))
    app.register("video", MenuScreen(video_menu, back="menu"))
    app.register("game", MenuScreen(game_menu, back="menu"))
    app.register("leaderboard_menu", MenuScreen(lb_menu, back="game")) # 追加
    app.register("name_entry", NameEntryScreen(back="game"))           # 追加
    app.register("leaderboard", LeaderboardScreen(back="leaderboard_menu")) # 追加
    from osagame.addvideo import EnterLinkScreen, VideoHistoryScreen
    app.register("addvideo", EnterLinkScreen(n_points))
    app.register("addvideo_history", VideoHistoryScreen())
    app.register("textbox", TextBoxDemoScreen())
    app.register("tetris", TetrisScreen(back="game"))
    app.register("pacman", PacmanScreen(back="game"))
    app.register("expline", MessageScreen("EXPLINE IS COMING SOON."))
    app.goto("home")
    return app


def _open_serial(args):
    """ポートを開いて、ESP32 からの文字を表示するスレッドを始める。(ser, stop) を返す。"""
    from osaconv.stream import _reader, open_port
    ser = open_port(args.port, args.baud, args.reset_wait)
    stop = threading.Event()
    threading.Thread(target=_reader, args=(ser, stop), daemon=True).start()
    return ser, stop


def _close_serial(ser, stop) -> None:
    stop.set()
    ser.close()


def _run_player(pg, args, osa: Path, wav: Path) -> str:
    """python -m osaconv.play を子プロセスで動かし、終わるまで待つ。Esc で中止。
    戻り値: "end"(最後まで再生した) / "stopped"(Esc などで止めた) / "quit"(ウィンドウが閉じられた)。
    "end" は、プレーヤーが終了コード 0 で終わったときだけ。"""
    cmd = [sys.executable, "-m", "osaconv.play", str(osa), "--audio", str(wav),
           "--port", args.port, "--baud", str(args.baud)]
    print("[osagame] run:", " ".join(cmd))
    result = None
    proc = subprocess.Popen(cmd, cwd=str(TOOLS_DIR))
    try:
        while proc.poll() is None:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    result = "quit"
                    proc.terminate()
                elif ev.type == pg.KEYDOWN and ev.key == pg.K_ESCAPE:
                    result = result or "stopped"
                    proc.terminate()
            pg.time.wait(50)
    except KeyboardInterrupt:
        result = result or "stopped"
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    print(f"[osagame] player finished (exit code {proc.returncode})")
    return result or ("end" if proc.returncode == 0 else "stopped")


# ------------------------------------------------------------------ pygame 側

def _translate(pg, ev):
    """pygame のイベント → (key, ch)。対象外なら None。"""
    if ev.type == pg.KEYDOWN:
        table = {
            pg.K_UP: "up", pg.K_DOWN: "down", pg.K_LEFT: "left", pg.K_RIGHT: "right",
            pg.K_RETURN: "enter", pg.K_KP_ENTER: "enter",
            pg.K_ESCAPE: "esc", pg.K_BACKSPACE: "backspace",
            pg.K_a: "a", pg.K_d: "d", pg.K_z: "z", pg.K_x: "x", pg.K_SPACE: "space"
        }
        if ev.key in table:
            return table[ev.key], None
    elif ev.type == pg.TEXTINPUT:
        return "char", ev.text
    return None

# ----------------------------------------------------------------------------
# tools/osagame/app.py の「# ------ pygame 側」以降(_draw_preview と main)の差し替え用。
#
# 差し替え手順:
#   1. app.py の先頭の import に、次の 2 行を足す
#          import time
#          import tracemalloc
#   2. app.py の _draw_preview() と main() を、このファイルの内容で置き換える
#      (_translate はそのまま残す)
#
# 変更点:
#   - _draw_preview: 1000 回の draw.line をやめ、ジャンプで区切った「連続した区間」ごとに
#     draw.lines で描く(Python のループが 1000 回 → 数回〜数十回に減る)
#   - dt の上限(0.1 秒): 一度重くなったときに、ゲームの時間が一気に進むのを防ぐ
#   - --profile: 5 秒ごとに、frame / write / preview / 待ち時間 / メモリ / スレッド数 を表示する
#   - --preview-every N: プレビューを N フレームに 1 回だけ描く(既定 1 = 毎フレーム)
# ----------------------------------------------------------------------------

# ------------------------------------------------------------------ pygame 側
 
def _draw_preview(pg, surface, xy: np.ndarray, scale: int = 2, jump: float = 24.0) -> None:
    """送っている点列を PC 画面にも描く。離れすぎた点どうしは線で結ばない(= ジャンプは見えない)。
 
    numpy でジャンプの位置を一括で求め、つながっている区間ごとに draw.lines で描く。
    """
    surface.fill((0, 12, 0))
    size = int(256 * scale)
    pts = xy.astype(np.int32) * scale
    pts[:, 1] = size - 1 - pts[:, 1]
 
    # 隣り合う点の距離(マンハッタン距離)が jump * scale を超えたところで区切る
    gaps = np.abs(np.diff(pts, axis=0)).sum(axis=1) > jump * scale
    cut = np.flatnonzero(gaps) + 1                 # 新しい区間が始まる位置
    for run in np.split(pts, cut):
        if len(run) >= 2:
            pg.draw.lines(surface, (60, 255, 90), False, run.tolist(), 1)
 
 
# ===== main ==============================
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="ホーム / メニュー / テキストボックスを ESP32 に表示する")
    ap.add_argument("--port", help="例: COM6(--no-serial のときは不要)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--points", type=int, default=1000, help="1 フレームの点数 N(.osa と合わせる)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--scale", type=float, default=1.0, help="表示倍率(X と Y の両方)。例: 0.485")
    ap.add_argument("--scale-x", type=float, default=None, help="X だけの倍率(省略で --scale)")
    ap.add_argument("--scale-y", type=float, default=None, help="Y だけの倍率(省略で --scale)")
    ap.add_argument("--home", nargs="?", const=str(HOME_OSA), default=str(HOME_OSA),
                    help=f"ホーム画面の .osa(省略・値なしで {HOME_OSA})")
    ap.add_argument("--no-serial", action="store_true", help="ESP32 に送らず、PC 画面だけ動かす")
    ap.add_argument("--no-preview", action="store_true", help="PC画面へのプレビュー描画をオフにする(本番の負荷軽減用)")
    ap.add_argument("--preview-every", type=int, default=1,
                    help="プレビューを N フレームに 1 回だけ描く(既定 1 = 毎フレーム)")
    ap.add_argument("--profile", action="store_true",
                    help="5 秒ごとに、処理時間・メモリ・スレッド数を表示する(重くなる原因の調査用)")
    ap.add_argument("--reset-wait", type=float, default=2.0)
    args = ap.parse_args(argv)
    if not args.no_serial and not args.port:
        ap.error("--port を指定してください(ESP32 なしなら --no-serial)")
    if not Path(args.home).is_file():
        sys.exit(f"[ERROR] ホーム用のファイルがありません: {args.home}")
    args.preview_every = max(1, args.preview_every)
 
    import pygame as pg
    from osaconv.stream import TYPE_FRAME_XY, build_packet
 
    app = build_app(args.points, args.home)
    app.audio = PygameAudio(pg)
    ser, stop = (None, None) if args.no_serial else _open_serial(args)
 
    pg.init()
    # プレビューなしの場合はウィンドウを小さくして邪魔にならないようにする
    win_size = (150, 150) if args.no_preview else (512, 512)
    surface = pg.display.set_mode(win_size)
    pg.display.set_caption("osagame" if args.no_preview else "osagame  (Up/Down, Enter, Esc)")
    pg.key.start_text_input()
    pg.key.set_repeat(350, 90)
    clock = pg.time.Clock()
    seq = 0
    frame_no = 0
 
    # ---- 調査用の計測(--profile のときだけ動く)
    prof = {"frame": 0.0, "write": 0.0, "prev": 0.0, "wait": 0.0, "n": 0}
    prof_t = time.perf_counter()
    profiler = cProfile.Profile() if args.profile else None
    cpu_t = time.process_time()
    if args.profile:
        tracemalloc.start()
 
    try:
        while app.running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    app.running = False
                    continue
                k = _translate(pg, ev)
                if k:
                    app.current.handle(app, *k)
 
            if app.launch is not None:
                osa, wav, after = app.launch
                app.launch = None
                if ser is None:
                    print("[osagame] --no-serial のときは再生できません")
                else:
                    _close_serial(ser, stop)
                    ser = None
 
                    result = _run_player(pg, args, osa, wav)
                    if result == "quit":
                        app.running = False
                    else:
                        ser, stop = _open_serial(args)
                        seq = 0
                        pg.event.clear()
                        if result == "end" and after:
                            app.goto(after)
 
                clock.tick()
                continue
 
            t0 = time.perf_counter()
            # 重くなったときに、ゲームの時間が一気に進まないよう dt に上限をつける
            dt = min(clock.tick(args.fps) / 1000.0, 0.1)
            t1 = time.perf_counter()
 
            if profiler is not None:
                profiler.enable()
            xy = app.current.frame(app, dt)
            if profiler is not None:
                profiler.disable()
            t2 = time.perf_counter()
 
            if ser is not None:
                ser.write(build_packet(TYPE_FRAME_XY, seq, xy.tobytes()))
                seq += 1
            t3 = time.perf_counter()
 
            if not args.no_preview:
                if frame_no % args.preview_every == 0:
                    _draw_preview(pg, surface, xy)
            else:
                surface.fill((0, 0, 0))    # プレビューを描画せず真っ暗にするだけ
            pg.display.flip()
            t4 = time.perf_counter()
            frame_no += 1
 
            if args.profile:
                prof["wait"] += t1 - t0
                prof["frame"] += t2 - t1
                prof["write"] += t3 - t2
                prof["prev"] += t4 - t3
                prof["n"] += 1
                if t4 - prof_t >= 5.0:
                    n = max(prof["n"], 1)
                    cur, peak = tracemalloc.get_traced_memory()
                    print(f"[prof] frame={prof['frame'] / n * 1000:5.1f}ms "
                          f"write={prof['write'] / n * 1000:5.1f}ms "
                          f"preview={prof['prev'] / n * 1000:5.1f}ms "
                          f"wait={prof['wait'] / n * 1000:5.1f}ms "
                          f"fps={n / (t4 - prof_t):4.1f} "
                          f"mem={cur / 1e6:6.1f}MB threads={threading.active_count()} "
                          f"screen={type(app.current).__name__}")
                    cpu_now = time.process_time()
                    print(f"        cpu_ratio={(cpu_now - cpu_t) / (t4 - prof_t):.2f}")
                    cpu_t = cpu_now
                    buf = io.StringIO()
                    pstats.Stats(profiler, stream=buf).sort_stats("cumulative").print_stats(8)
                    print(buf.getvalue())
                    profiler = cProfile.Profile()
                    prof.update(frame=0.0, write=0.0, prev=0.0, wait=0.0, n=0)
                    prof_t = t4
    except KeyboardInterrupt:
        pass
    finally:
        app.audio.stop()
        if ser is not None:
            _close_serial(ser, stop)
        pg.quit()
 
 
if __name__ == "__main__":
    main()
 