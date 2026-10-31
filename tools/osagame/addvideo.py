"""VIDEO > ENTER THE RINK / HISTORY。YouTube の動画を、オシロで流せる形(.osa + .wav)にして再生する。

流れ:
    1. ENTER THE RINK を選ぶ → 入力画面。`youtube.com/watch?v=` の「=」以降(動画 ID 11 文字)をキーボードで入力
    2. Enter → yt-dlp(1 回だけ)で動画を探す(CHECKING...)
         失敗: FAILED / TRY AGAIN を出して、入力し直し
         成功: SUCCESS / PLZ WAITING... を出したまま、裏で mp4 のダウンロード → .osa と .wav の作成
               (ffmpeg 1 本が、縮小したグレー画像と wav を同時に出し、画像から輪郭を取る)
    3. .osa と .wav がそろったら、そのまま再生(osaconv.play を子プロセスで起動 = BADAPPLE と同じ経路)
    4. 再生した動画は history.json に残り、VIDEO > HISTORY から選んで、また再生できる

保存先: tools/source/addvideo/  <名前>.mp4(残す。再変換のときは再ダウンロードしない) / .osa / .wav / history.json

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
import time
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

# 輪郭抽出なので低画質で十分。H.264(avc1)なら、ダウンロードも展開も速い。音声つき 1 本のものを優先(結合の手間が無い)
YT_FORMAT = ("b[height<=360][vcodec^=avc1]/bv*[height<=360][vcodec^=avc1]+ba/"
             "b[height<=360]/bv*[height<=360]+ba/b")
MAX_SIDE = 256                   # 変換に使う画像の長辺(px)。オシロは 0〜255 の範囲しか使えないので、これ以上は無駄
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov")
DOWNLOAD_TIMEOUT = 900


class _Cancelled(Exception):
    pass


def find_video(video_id: str) -> Path | None:
    """ダウンロード済みの動画ファイル(source/addvideo/ に残してある)。無ければ None。"""
    stem = file_stem(video_id)
    for ext in VIDEO_EXTS:
        p = ADDVIDEO_DIR / f"{stem}{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def parse_info_line(line: str) -> tuple[float, bool, str]:
    """yt-dlp が最初に出す 1 行 "長さ<TAB>ライブか<TAB>タイトル" → (長さ秒, ライブか, タイトル)。"""
    parts = line.rstrip("\r\n").split("\t", 2) + ["", ""]
    try:
        duration = float(parts[0])
    except ValueError:
        duration = 0.0
    return duration, parts[1] == "True", parts[2]


def scaled_size(w: int, h: int, max_side: int = MAX_SIDE) -> tuple[int, int]:
    """長辺が max_side になるように縮小したサイズ(拡大はしない)。"""
    k = min(1.0, max_side / max(w, h))
    return max(2, round(w * k)), max(2, round(h * k))


class Job(threading.Thread):
    """動画 ID から .osa / .wav を作る。stage: check → work → ready / failed。

    流れ: yt-dlp(1 回だけ)で mp4 を保存 → ffmpeg 1 本が「縮小したグレー画像(パイプ)」と「wav」を同時に出す
          → グレー画像から輪郭 → .osa
    """

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
        self._tmp_dirs: list[Path] = []

    # ---- 外から使う
    def cancel(self) -> None:
        self._cancel.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    # ---- 部品
    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise _Cancelled

    def _mkdtemp(self, prefix: str) -> Path:
        d = Path(tempfile.mkdtemp(prefix=prefix, dir=ADDVIDEO_DIR))
        self._tmp_dirs.append(d)
        return d

    def _run_cmd(self, cmd: list[str], timeout: float | None = None) -> str:
        self._check_cancel()
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
        self._check_cancel()
        if rc != 0:
            raise RuntimeError((err or "").strip()[-400:] or f"exit code {rc}")
        return out

    def probe(self, video: Path) -> tuple[int, int, float, bool]:
        """(幅, 高さ, 長さ秒, 音声があるか)。"""
        out = self._run_cmd([_tool("ffprobe"), "-v", "error",
                             "-show_entries", "stream=codec_type,width,height:format=duration",
                             "-of", "json", str(video)], timeout=30)
        d = json.loads(out)
        streams = d.get("streams", [])
        st = next(x for x in streams if x.get("codec_type") == "video")
        has_audio = any(x.get("codec_type") == "audio" for x in streams)
        try:
            dur = float(d.get("format", {}).get("duration") or 0)
        except ValueError:
            dur = 0.0
        return int(st["width"]), int(st["height"]), dur, has_audio

    # ---- 1) 動画を手に入れる(保存済みならそれを使う)
    def acquire(self) -> Path:
        """動画ファイルを返す。stage を work にして、title / total_sec を埋める。"""
        vid = self.video_id
        saved = find_video(vid)
        if saved is not None:                                    # 前に保存した mp4 がある → ダウンロード不要
            self.title = next((e.get("title", "") for e in load_history() if e["id"] == vid), "")
            self.phase, self.stage = "CONVERT", "work"
            return saved

        tmp = self._mkdtemp("dl_")
        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "-q", "--no-progress",
               # 最初の 1 行(長さ・ライブか・タイトル)が出た = 動画が見つかった。そのままダウンロードを続ける
               "--print", "before_dl:%(duration)s\t%(is_live)s\t%(title)s", "--no-simulate",
               "-N", "4", "-f", YT_FORMAT, "-o", str(tmp / "video.%(ext)s"), WATCH_URL + vid]
        self._check_cancel()
        errf = tempfile.TemporaryFile()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True,
                                encoding="utf-8", errors="replace",
                                env={**os.environ, "PYTHONUTF8": "1"})
        self._proc = proc
        watchdog = threading.Timer(DOWNLOAD_TIMEOUT, proc.kill)
        watchdog.start()
        try:
            line = proc.stdout.readline()
            if not line:
                proc.wait()
                self._check_cancel()
                errf.seek(0)
                raise RuntimeError(errf.read().decode("utf-8", "replace").strip()[-400:] or "video not found")
            duration, is_live, title = parse_info_line(line)
            if is_live:
                raise RuntimeError("live stream is not supported")
            if duration > MAX_DURATION_SEC:
                raise RuntimeError(f"video is too long (limit {MAX_DURATION_SEC // 60} min)")
            self.title, self.total_sec = title, duration
            self.phase, self.stage = "DOWNLOAD", "work"          # ← ここで SUCCESS
            proc.stdout.read()                                   # ダウンロードが終わるまで待つ
            rc = proc.wait()
            self._check_cancel()
            if rc != 0:
                errf.seek(0)
                raise RuntimeError(errf.read().decode("utf-8", "replace").strip()[-400:] or f"exit code {rc}")
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            raise
        finally:
            watchdog.cancel()
            self._proc = None
            errf.close()
        files = [p for p in tmp.glob("video.*") if p.suffix in VIDEO_EXTS]
        if not files:
            raise RuntimeError("download produced no file")
        dest = ADDVIDEO_DIR / f"{file_stem(vid)}{files[0].suffix}"
        os.replace(files[0], dest)                               # mp4 は、そのまま残す
        return dest

    # ---- 2) mp4 → .osa と .wav
    def _on_progress(self, sec: float) -> None:
        self.sec = sec

    def process(self, video: Path, out_osa: Path, out_wav: Path) -> dict:
        """ffmpeg 1 本で「縮小したグレー画像」をパイプに流しつつ wav も書き、画像から輪郭 → .osa を作る。"""
        from osaconv.contour import ContourParams, frame_to_contours
        from osaconv.pack import OsaWriter
        from osaconv.path import contours_to_path

        w, h, dur, has_audio = self.probe(video)
        if not self.total_sec:
            self.total_sec = dur
        sw, sh = scaled_size(w, h)
        frame_bytes = sw * sh
        cmd = [_tool("ffmpeg"), "-v", "error", "-i", str(video),
               # 出力 1: 画像(fps を 30 にそろえ、縮小して、グレーにして、パイプへ)
               "-map", "0:v:0", "-an", "-vf", f"fps={FPS},scale={sw}:{sh}:flags=area,format=gray",
               "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
        if has_audio:                       # 出力 2: 音声(16bit PCM / 2ch / 44100Hz)。無い動画では付けない
            cmd += ["-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(AUDIO_RATE), "-c:a", "pcm_s16le",
                    "-y", str(out_wav)]
        self.phase, self.sec = "CONVERT", 0.0
        params = ContourParams()
        frames = 0
        errf = tempfile.TemporaryFile()
        self._check_cancel()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf)
        self._proc = proc
        try:
            with OsaWriter(out_osa, fps=FPS, points_per_frame=self.n_points) as writer:
                while True:
                    buf = proc.stdout.read(frame_bytes)
                    if len(buf) < frame_bytes:
                        break
                    self._check_cancel()
                    gray = np.frombuffer(buf, dtype=np.uint8).reshape(sh, sw)
                    contours = frame_to_contours(gray, params)
                    writer.write_frame(contours_to_path(contours, gray.shape, self.n_points))
                    frames += 1
                    if frames % 15 == 0:
                        self._on_progress(frames / FPS)
            rc = proc.wait()
            self._check_cancel()
            if frames == 0:
                errf.seek(0)
                raise RuntimeError(errf.read().decode("utf-8", "replace").strip()[-400:] or f"ffmpeg exit {rc}")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            self._proc = None
            errf.close()
        self._on_progress(frames / FPS)
        if not out_wav.is_file() or out_wav.stat().st_size <= 44:   # 音声が無い動画 → 無音の wav
            self.phase = "AUDIO"
            write_silent_wav(out_wav, frames / FPS)
        return {"frames": frames, "seconds": frames / FPS}

    def run(self) -> None:
        vid = self.video_id
        try:
            ADDVIDEO_DIR.mkdir(parents=True, exist_ok=True)
            if is_cached(vid):                                    # 変換済みなら、すぐ再生できる
                self.title = next((e.get("title", "") for e in load_history() if e["id"] == vid), "")
                self.stage = "ready"
                return
            t0 = time.perf_counter()
            video = self.acquire()                                # ← ここを通れば SUCCESS
            t1 = time.perf_counter()
            tmp = self._mkdtemp("out_")
            osa, wav = video_paths(vid)
            stats = self.process(video, tmp / "out.osa", tmp / "out.wav")
            self._check_cancel()
            os.replace(tmp / "out.wav", wav)                      # 2 つがそろった時点で ready
            os.replace(tmp / "out.osa", osa)
            t2 = time.perf_counter()
            print(f"[addvideo] {vid}: download {t1 - t0:.1f}s, convert {t2 - t1:.1f}s "
                  f"({stats['seconds'] / max(t2 - t1, 1e-6):.1f}x realtime)")
            self.stage = "ready"
        except _Cancelled:
            self.stage = "cancelled"
        except Exception as e:                                    # noqa: BLE001 失敗は全部 FAILED にする
            self.error = str(e)
            print(f"[addvideo] FAILED {vid}: {e}")
            self.stage = "failed"
        finally:
            for d in self._tmp_dirs:
                shutil.rmtree(d, ignore_errors=True)


def write_silent_wav(path: Path, seconds: float) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(AUDIO_RATE)
        w.writeframes(bytes(int(seconds * AUDIO_RATE) * 4))


def _tool(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        raise RuntimeError(f"{name} was not found on PATH")
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