"""VIDEO > ENTER THE RINK / HISTORY。YouTube の動画を、オシロで流せる形(.osa + .wav)にして再生する。

流れ:
    1. ENTER THE RINK を選ぶ → 入力画面。`youtube.com/watch?v=` の「=」以降(動画 ID 11 文字)をキーボードで入力
    2. Enter → yt-dlp で動画の情報を取得(CHECKING...)
         失敗: FAILED / TRY AGAIN を出して、入力し直し
         成功: SUCCESS / PLZ WAITING... を出したまま、裏で ダウンロード → .osa 変換 → .wav 作成
    3. .osa と .wav がそろったら、そのまま再生(osaconv.play を子プロセスで起動 = BADAPPLE と同じ経路)
    4. 再生した動画は history.json に残り、VIDEO > HISTORY から選んで、また再生できる

保存先: tools/source/addvideo/<動画ID>.osa, <動画ID>.wav, history.json

必要なもの: `pip install yt-dlp`、ffmpeg(PATH に通す)
画面(Screen)は pygame に依存しない。重い処理は別スレッド(Job)で行うので、その間も ESP32 には
フレームを送り続けられる(ESP32 は 1 秒以上途切れると動く円に戻るため)。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from osagame.font import ADVANCE, CELL_H, GLYPHS
from osagame.screens import SE_ENTER, SE_MOVE, Screen, play_se
from osagame.ui import TextBox, center_x, rect_polyline, text_to_polylines

TOOLS_DIR = Path(__file__).resolve().parents[1]               # tools/
ADDVIDEO_DIR = TOOLS_DIR / "source" / "addvideo"              # 保存先
HISTORY_JSON = ADDVIDEO_DIR / "history.json"
WATCH_URL = "https://www.youtube.com/watch?v="                # ?v= までは、あらかじめ入れてある

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_DURATION_SEC = 15 * 60       # これより長い動画は受け付けない(変換に時間がかかりすぎるため)
MAX_HISTORY = 100
FPS = 30
AUDIO_RATE = 44100


# ------------------------------------------------------------------ 入力・パス・履歴(純粋な関数)

def parse_video_id(text: str) -> str | None:
    """入力文字列 → 動画 ID。ID そのもの、または URL(watch?v= / youtu.be)を受け付ける。不正なら None。"""
    s = (text or "").strip()
    m = re.search(r"(?:[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", s)
    if m:
        return m.group(1)
    return s if VIDEO_ID_RE.match(s) else None


def file_stem(video_id: str) -> str:
    """ファイル名(拡張子なし)。動画 ID は大文字小文字を区別するが、Windows / macOS のファイル名は
    区別しない。大小だけが違う別の動画がぶつからないよう、ID のハッシュを足す。"""
    return f"{video_id.lower()}_{hashlib.sha1(video_id.encode()).hexdigest()[:6]}"


def video_paths(video_id: str) -> tuple[Path, Path]:
    stem = file_stem(video_id)
    return ADDVIDEO_DIR / f"{stem}.osa", ADDVIDEO_DIR / f"{stem}.wav"


def is_cached(video_id: str) -> bool:
    osa, wav = video_paths(video_id)
    return osa.is_file() and wav.is_file() and osa.stat().st_size > 0


def load_history() -> list[dict]:
    """新しい順の履歴。[{id, title, played_at}, ...]"""
    try:
        data = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and VIDEO_ID_RE.match(str(e.get("id", "")))]
    except (OSError, ValueError):
        return []


def add_history(video_id: str, title: str = "") -> None:
    """再生した動画を履歴の先頭に入れる(同じ動画は 1 つにまとめる)。"""
    entries = load_history()
    if not title:
        title = next((e.get("title", "") for e in entries if e["id"] == video_id), "")
    entries = [e for e in entries if e["id"] != video_id]
    entries.insert(0, {"id": video_id, "title": title,
                       "played_at": datetime.now().isoformat(timespec="seconds")})
    ADDVIDEO_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries[:MAX_HISTORY], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, HISTORY_JSON)


def display_name(entry: dict, max_len: int) -> str:
    """オシロのフォントで描ける文字だけにした表示名。描けなければ動画 ID。"""
    title = "".join(c for c in str(entry.get("title", "")).upper() if c in GLYPHS)
    title = " ".join(title.split())
    return (title if len(title) >= 3 else entry["id"])[:max_len]


# ------------------------------------------------------------------ 取得・変換のジョブ(別スレッド)

class _Cancelled(Exception):
    pass


class Job(threading.Thread):
    """動画 ID から .osa / .wav を作る。stage: check → work → ready / failed。"""

    def __init__(self, video_id: str, n_points: int):
        super().__init__(daemon=True)
        self.video_id, self.n_points = video_id, n_points
        self.stage = "check"
        self.title = ""
        self.error = ""
        self.phase = ""                  # 今していること: DOWNLOAD / CONVERT / AUDIO
        self.sec = 0.0                   # 変換で、いま処理している位置(秒)
        self.total_sec = 0.0             # 動画の長さ(秒)。分からなければ 0
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None

    # ---- 外から使う
    def cancel(self) -> None:
        self._cancel.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    # ---- 中身
    def _run_cmd(self, cmd: list[str], timeout: float | None = None) -> str:
        if self._cancel.is_set():
            raise _Cancelled
        env = {**os.environ, "PYTHONUTF8": "1"}
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8", errors="replace", env=env)
        try:
            out, err = self._proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.communicate()
            raise RuntimeError("timeout: " + " ".join(cmd[:3]))
        finally:
            rc = self._proc.returncode
            self._proc = None
        if self._cancel.is_set():
            raise _Cancelled
        if rc != 0:
            raise RuntimeError((err or "").strip()[-400:] or f"exit code {rc}")
        return out

    def fetch_info(self) -> dict:
        out = self._run_cmd([sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
                             "-J", WATCH_URL + self.video_id], timeout=60)
        info = json.loads(out)
        if info.get("is_live"):
            raise RuntimeError("live stream is not supported")
        if (info.get("duration") or 0) > MAX_DURATION_SEC:
            raise RuntimeError(f"video is too long (limit {MAX_DURATION_SEC // 60} min)")
        return info

    def download(self, tmp: Path) -> Path:
        self._run_cmd([sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "-q",
                       # 輪郭抽出なので低画質で十分。cv2 で開ける mp4 を優先する
                       "-f", "b[height<=360][ext=mp4]/bv*[height<=360][ext=mp4]+ba[ext=m4a]/"
                             "b[height<=360]/bv*[height<=360]+ba/b",
                       "-o", str(tmp / "video.%(ext)s"), WATCH_URL + self.video_id], timeout=900)
        files = [p for p in tmp.glob("video.*") if p.suffix not in (".part", ".ytdl")]
        if not files:
            raise RuntimeError("download produced no file")
        return files[0]

    def _on_progress(self, sec: float) -> None:
        self.sec = sec
        if self._cancel.is_set():
            raise _Cancelled                                 # 変換の途中でも、Esc で止められる

    def convert(self, video: Path, out_osa: Path, tmp: Path) -> dict:
        from osaconv.convert import convert_video
        self.phase, self.sec = "CONVERT", 0.0
        try:
            stats = convert_video(video, out_osa, fps=FPS, n_points=self.n_points,
                                  on_progress=self._on_progress)
        except RuntimeError:
            # cv2 が開けない形式(VP9 など)は、ffmpeg で H.264 にしてもう一度
            fixed = tmp / "fixed.mp4"
            self._run_cmd([_ffmpeg(), "-y", "-v", "error", "-i", str(video), "-an",
                           "-c:v", "libx264", "-preset", "veryfast", str(fixed)])
            self.sec = 0.0
            stats = convert_video(fixed, out_osa, fps=FPS, n_points=self.n_points,
                                  on_progress=self._on_progress)
        if stats["frames"] <= 0:
            raise RuntimeError("no frames were converted")
        return stats

    def make_wav(self, video: Path, out_wav: Path, seconds: float) -> None:
        """16bit PCM / 2ch / 44100Hz の WAV にする。音声が無い動画は、無音の WAV を作る。"""
        self.phase = "AUDIO"
        try:
            self._run_cmd([_ffmpeg(), "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "2",
                           "-ar", str(AUDIO_RATE), "-c:a", "pcm_s16le", str(out_wav)])
            if out_wav.is_file() and out_wav.stat().st_size > 44:
                return
        except RuntimeError:
            pass
        with wave.open(str(out_wav), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(AUDIO_RATE)
            w.writeframes(bytes(int(seconds * AUDIO_RATE) * 4))

    def run(self) -> None:
        vid = self.video_id
        tmp = None
        try:
            ADDVIDEO_DIR.mkdir(parents=True, exist_ok=True)
            if is_cached(vid):                                    # 変換済みなら、すぐ再生できる
                self.title = next((e.get("title", "") for e in load_history() if e["id"] == vid), "")
                self.stage = "ready"
                return
            info = self.fetch_info()                              # ← ここが通れば SUCCESS
            self.title = str(info.get("title") or "")
            self.total_sec = float(info.get("duration") or 0)
            self.phase = "DOWNLOAD"
            self.stage = "work"
            tmp = Path(tempfile.mkdtemp(prefix=f"{vid}_", dir=ADDVIDEO_DIR))
            video = self.download(tmp)
            osa, wav = video_paths(vid)
            tmp_osa, tmp_wav = tmp / "out.osa", tmp / "out.wav"
            stats = self.convert(video, tmp_osa, tmp)
            self.make_wav(video, tmp_wav, stats["seconds"])
            if self._cancel.is_set():
                raise _Cancelled
            os.replace(tmp_wav, wav)                              # 2 つがそろった時点で ready
            os.replace(tmp_osa, osa)
            self.stage = "ready"
        except _Cancelled:
            self.stage = "cancelled"
        except Exception as e:                                    # noqa: BLE001 失敗は全部 FAILED にする
            self.error = str(e)
            print(f"[addvideo] FAILED {vid}: {e}")
            self.stage = "failed"
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("ffmpeg was not found on PATH")
    return exe


def launch_video(app, video_id: str, title: str = "") -> None:
    """履歴に入れて、VIDEO メニューに戻してから再生を依頼する(止めたときも、再生が終わったときも VIDEO に戻る)。"""
    add_history(video_id, title)
    osa, wav = video_paths(video_id)
    app.goto("video")
    app.play_video(osa, wav, after="video")


# ------------------------------------------------------------------ 画面

def progress_label(phase: str, sec: float, total: float) -> str:
    """進捗の文字。例: "CONVERT 12/180 SEC"。長さが分からないときは "CONVERT 12 SEC"。"""
    if phase == "CONVERT":
        if total > 0:
            return f"CONVERT {int(min(sec, total))}/{int(total)} SEC"
        return f"CONVERT {int(sec)} SEC"
    return {"DOWNLOAD": "DOWNLOADING...", "AUDIO": "MAKING AUDIO..."}.get(phase, "")


def progress_polylines(phase: str, sec: float, total: float) -> list[np.ndarray]:
    """進捗の文字と、進み具合のバー。"""
    label = progress_label(phase, sec, total)
    polys = text_to_polylines(label, center_x(label, 10), 82, 10) if label else []
    if phase == "CONVERT" and total > 0:
        frac = max(0.0, min(1.0, sec / total))
        polys.append(rect_polyline(16, 56, 224, 12))
        if frac > 0:
            polys.append(rect_polyline(16, 56, 224 * frac, 12))
    elif phase == "AUDIO":
        polys.append(rect_polyline(16, 56, 224, 12))
        polys.append(rect_polyline(16, 56, 224, 12))
    return polys


class IdBox(TextBox):
    """動画 ID 用の 1 行入力欄。ストロークフォントは大文字しか無いので、小文字は小さく描いて、
    大小を見分けられるようにする。カーソルは、ID に使える "_" と区別するため、下線で描く。"""
    LOWER_W, LOWER_H = 0.8, 0.6          # 小文字の、幅と高さの倍率(大文字 = 1.0)

    def polylines(self) -> list[np.ndarray]:
        s = self.size / CELL_H
        x0 = self.x + self.pad
        y0 = self.y + (self.h - self.size) / 2
        polys = [rect_polyline(self.x, self.y, self.w, self.h)]
        for i, ch in enumerate(self.text):
            glyph = GLYPHS.get(ch.upper(), GLYPHS["?"])
            sx, sy = (s * self.LOWER_W, s * self.LOWER_H) if ch.islower() else (s, s)
            ox = x0 + i * ADVANCE * s
            for stroke in glyph:
                polys.append(np.array([(ox + px * sx, y0 + py * sy) for px, py in stroke], dtype=np.float64))
        if int(self._t * 2) % 2 == 0:
            cx = x0 + len(self.text) * ADVANCE * s
            polys.append(np.array([(cx, y0 - 3), (cx + 4 * s, y0 - 3)], dtype=np.float64))
        return polys


class EnterLinkScreen(Screen):
    """URL の入力 → 取得 → 変換 → 再生。"""
    FAIL_SEC = 2.0

    def __init__(self, n_points: int):
        self.n_points = n_points
        self.state = "input"            # input / check / work / failed
        self.job: Job | None = None
        self.preset: str | None = None  # HISTORY から、変換し直しで来たときの動画 ID
        self.timer = 0.0
        self.msg = TextBox(16, 122, 224, 84, size=11, cps=30.0)
        self.inp = IdBox(16, 50, 224, 40, input_mode=True, size=14, max_len=11)

    # ---- 状態の切り替え
    def _to_input(self) -> None:
        self.state = "input"
        self.inp.set_text("", typewriter=False)
        self.msg.set_text("PLZ ENTER THE LINK\n(AND PRESS ENTER)")

    def _to_failed(self) -> None:
        self.state, self.timer = "failed", 0.0
        self.msg.set_text("FAILED\nTRY AGAIN")

    def _start(self, video_id: str) -> None:
        self.state = "check"
        self.msg.set_text("CHECKING...")
        self.job = Job(video_id, self.n_points)
        self.job.start()

    def _cancel_job(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.job = None

    def on_enter(self, app) -> None:
        self._cancel_job()
        self._to_input()
        if self.preset:                                  # 履歴から(ファイルが消えていたとき)
            vid, self.preset = self.preset, None
            self._start(vid)

    # ---- 入力
    def handle(self, app, key, ch=None) -> None:
        if key == "esc":
            self._cancel_job()
            app.goto("video")
        elif self.state != "input":
            return
        elif key == "char" and ch:
            self.inp.append(ch)
        elif key == "backspace":
            self.inp.backspace()
        elif key == "enter":
            vid = parse_video_id(self.inp.text)
            if vid:
                self._start(vid)
            else:
                self._to_failed()                        # 形が違う入力も、取得失敗と同じ扱い

    # ---- 毎フレーム
    def frame(self, app, dt: float):
        job = self.job
        if job is not None:
            if job.stage == "work" and self.state == "check":
                self.state = "work"
                self.msg.set_text("SUCCESS\nPLZ WAITING...")
            elif job.stage == "ready":
                self.job = None
                launch_video(app, job.video_id, job.title)
                return app.current.frame(app, 0.0)
            elif job.stage == "failed":
                self.job = None
                self._to_failed()
        if self.state == "failed":
            self.timer += dt
            if self.timer >= self.FAIL_SEC:
                self._to_input()
        return super().frame(app, dt)

    def polylines(self, app, dt: float) -> list:
        self.msg.update(dt)
        self.inp.update(dt)
        polys = self.msg.polylines()
        if self.state == "input":
            label = "YOUTUBE.COM/WATCH?V="
            polys += text_to_polylines(label, center_x(label, 8), 98, 8)
            polys += self.inp.polylines()
        elif self.state == "work" and self.job is not None:
            polys += progress_polylines(self.job.phase, self.job.sec, self.job.total_sec)
        return polys


class VideoHistoryScreen(Screen):
    """再生した動画の一覧。↑↓ で選んで Enter で、もう一度再生する。"""
    ROWS = 5

    def __init__(self, enter_screen: str = "addvideo"):
        self.enter_screen = enter_screen
        self.entries: list[dict] = []
        self.index = 0
        self.top = 0
        self.t = 0.0

    def on_enter(self, app) -> None:
        self.entries = load_history()
        self.index = self.top = 0

    def handle(self, app, key, ch=None) -> None:
        if key == "esc":
            app.goto("video")
        elif not self.entries:
            return
        elif key == "up":
            self.index = (self.index - 1) % len(self.entries)
            play_se(app, SE_MOVE)
        elif key == "down":
            self.index = (self.index + 1) % len(self.entries)
            play_se(app, SE_MOVE)
        elif key == "enter":
            play_se(app, SE_ENTER)
            e = self.entries[self.index]
            if is_cached(e["id"]):
                launch_video(app, e["id"], e.get("title", ""))
            else:                                        # ファイルが消えていたら、取得からやり直す
                app.screens[self.enter_screen].preset = e["id"]
                app.goto(self.enter_screen)
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + self.ROWS:
            self.top = self.index - self.ROWS + 1

    def polylines(self, app, dt: float) -> list:
        self.t += dt
        title = "HISTORY"
        polys = text_to_polylines(title, center_x(title, 18), 228, 18)
        polys.append(np.array([(22.0, 218.0), (233.0, 218.0)]))
        if not self.entries:
            polys += text_to_polylines("NO HISTORY", center_x("NO HISTORY", 12), 130, 12)
        for row in range(self.ROWS):
            i = self.top + row
            if i >= len(self.entries):
                break
            y = 185 - row * 32
            polys += text_to_polylines(display_name(self.entries[i], 20), 30, y, 10)
            if i == self.index:
                bob = 2.5 * (0.5 + 0.5 * np.sin(self.t * 2 * np.pi * 1.5))
                polys += text_to_polylines(">", 12 + bob, y, 10)
        hint = "UP/DOWN  ENTER:PLAY  ESC:BACK"
        polys += text_to_polylines(hint, center_x(hint, 7), 12, 7)
        return polys