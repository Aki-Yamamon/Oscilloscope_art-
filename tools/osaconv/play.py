"""映像（.osa）を ESP32 に送りながら、同じ時刻の音声を PC で鳴らす（v0.3.0）。

    python -m osaconv.play main.osa --audio audio_clip.wav --port COM6 --baud 921600
    python -m osaconv.play full.osa --audio audio_full.wav --port COM6 --baud 921600 --loop

同期の考え方:
    時間の基準（マスタークロック）は「音声」。映像のフレームは、音が今どこまで進んでいるかを見て、
    その位置のフレームを送る。PC の時計と音声デバイスの時計は、わずかに速さが違い、長く再生するとずれる。
    音声を基準にすれば、どれだけ再生しても、音と映像は離れない。

    今聞こえている音の位置:  pos = S / sr + (今 - T) - latency
        S: 音声コールバックが、これから出力するブロックの先頭のサンプル番号
        T: そのコールバックが呼ばれた時刻   latency: 出力デバイスの遅延（秒）
    送るフレーム:  floor((pos + offset + lead) * fps)
        offset: 手で合わせる補正（秒）。+ にすると映像が先に出る
        lead:   1 フレームの送信にかかる時間（シリアルの転送時間）。自動で足す

詳しい仕様は docs/AUDIO_SYNC_SPEC.md。
"""
from __future__ import annotations

import argparse
import math
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from osaconv.pack import read_osa
from osaconv.stream import CTRL_END, TYPE_FRAME_XY, _reader, build_control, build_packet, open_port


class AudioClock:
    """音声の再生位置（秒）を、音声コールバックの記録から推定する。

    コールバックは 10〜20ms ごとにしか呼ばれないので、その間は PC の時計で補間する。
    コールバックのたびに、音声の位置に合わせ直すので、PC の時計の狂いは溜まらない。
    """

    def __init__(self, sample_rate: int, latency_s: float = 0.0, time_fn=time.perf_counter):
        self.sample_rate = sample_rate
        self.latency_s = latency_s
        self._time = time_fn
        self._lock = threading.Lock()
        self._start_sample = 0
        self._t_cb: float | None = None

    def on_block(self, start_sample: int) -> None:
        """音声コールバックの先頭で呼ぶ。start_sample = これから出すブロックの先頭のサンプル番号。"""
        t = self._time()
        with self._lock:
            self._start_sample = start_sample
            self._t_cb = t

    def position(self) -> float | None:
        """今、聞こえている音の位置（秒）。まだ音声が始まっていなければ None。"""
        with self._lock:
            if self._t_cb is None:
                return None
            start, t_cb = self._start_sample, self._t_cb
        return start / self.sample_rate + (self._time() - t_cb) - self.latency_s


def load_wav(path) -> tuple[np.ndarray, int]:
    """16bit PCM の WAV を読む。戻り値: (shape (サンプル数, チャンネル数) の int16 配列, サンプリングレート)"""
    with wave.open(str(path), "rb") as w:
        ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError("16bit PCM の WAV だけ対応しています（ffmpeg に -c:a pcm_s16le を付ける）")
    return np.frombuffer(raw, dtype="<i2").reshape(-1, ch), sr


def fit_audio(data: np.ndarray, n_samples: int) -> np.ndarray:
    """音声の長さを、映像の長さ（n_samples）にそろえる。足りなければ無音で埋め、余れば切る。"""
    if len(data) >= n_samples:
        return np.ascontiguousarray(data[:n_samples])
    pad = np.zeros((n_samples - len(data), data.shape[1]), dtype=data.dtype)
    return np.concatenate([data, pad])


@dataclass
class PlayStats:
    sent: int = 0
    skipped: int = 0


def run_sender(ser, xy: np.ndarray, fps: int, clock, *, duration_s: float, loop: bool = False,
               lead_s: float = 0.0, get_offset_s=lambda: 0.0, stop: threading.Event | None = None,
               on_second=None, poll_s: float = 0.001) -> PlayStats:
    """音声の位置に合わせて、フレームを送り続ける。

    xy: (フレーム数, N, 2) の uint8。clock: position() を持つもの（AudioClock など）。
    duration_s: 映像の長さ（秒）。loop=False なら、その長さで終わる。
    """
    total = len(xy)
    stop = stop or threading.Event()
    st = PlayStats()
    last = -1                         # 最後に送ったフレームの「通し」番号（ループでは total を超えて増える）
    seq = 0
    last_report = time.perf_counter()

    while not stop.is_set():
        pos = clock.position()
        if pos is None:               # 音声がまだ始まっていない
            time.sleep(poll_s)
            continue
        t = pos + get_offset_s() + lead_s
        if t < 0:
            time.sleep(poll_s)
            continue
        if not loop and t >= duration_s:
            break
        target = int(math.floor(t * fps))
        if target > last:
            if last >= 0 and target > last + 1:
                st.skipped += target - last - 1       # 1 フレーム以上遅れた: 飛ばして、音に合わせる
            ser.write(build_packet(TYPE_FRAME_XY, seq, xy[target % total].tobytes()))
            seq += 1
            st.sent += 1
            last = target
        else:
            time.sleep(poll_s)

        if on_second is not None and time.perf_counter() - last_report >= 1.0:
            last_report = time.perf_counter()
            on_second(st, pos, target % total, get_offset_s())

    if not loop and not stop.is_set():
        ser.write(build_control(seq, CTRL_END))        # 映像が終わった: ESP32 を、すぐ待機パターンへ
    return st


def play_av(osa_path, wav_path, port: str, baud: int, offset_ms: float = 0.0, loop: bool = False,
            reset_wait: float = 2.0) -> None:
    import sounddevice as sd          # pip install sounddevice

    header, xy, _ = read_osa(osa_path)
    fps, total = header.fps, header.frame_count
    duration_s = total / fps
    data, sr = load_wav(wav_path)
    n_samples = int(round(duration_s * sr))
    audio = fit_audio(data, n_samples)
    print(f"映像 {duration_s:.1f}s / 音声 {len(data) / sr:.1f}s（映像の長さにそろえる）/ {sr}Hz / {audio.shape[1]}ch")

    ser = open_port(port, baud, reset_wait)
    stop = threading.Event()
    threading.Thread(target=_reader, args=(ser, stop), daemon=True).start()

    offset = {"s": offset_ms / 1000.0}
    lead_s = (2 * header.points_per_frame + 11) * 10.0 / baud      # 1 パケットの転送時間
    print(f"自動で足す先行 lead = {lead_s * 1000:.1f} ms / 手動 offset = {offset_ms:+.0f} ms")

    def key_thread():                 # 実行中に「+10」「-10」と入力して Enter で、offset を調整できる
        for line in sys.stdin:
            try:
                offset["s"] += int(line.strip()) / 1000.0
                print(f">>> offset = {offset['s'] * 1000:+.0f} ms（次回は --offset-ms {offset['s'] * 1000:.0f}）")
            except ValueError:
                print(">>> 数字で入力してください（例: +10 や -10）")
    threading.Thread(target=key_thread, daemon=True).start()

    clock = AudioClock(sr)
    state = {"pos": 0, "underflow": 0}

    def callback(outdata, frames, time_info, status):
        if status:
            state["underflow"] += 1
        pos = state["pos"]
        clock.on_block(pos)           # この時刻に、サンプル pos から出力する、と記録する
        if loop:
            outdata[:] = audio[np.arange(pos, pos + frames) % n_samples]
        else:
            k = max(min(pos + frames, n_samples) - pos, 0)
            outdata[:k] = audio[pos:pos + k]
            outdata[k:] = 0
        state["pos"] = pos + frames

    def report(st: PlayStats, pos: float, frame: int, off: float) -> None:
        print(f"[PC] t={pos:6.2f}s frame={frame}/{total} sent={st.sent} skipped={st.skipped} "
              f"offset={off * 1000:+.0f}ms underflow={state['underflow']}")

    try:
        with sd.OutputStream(samplerate=sr, channels=audio.shape[1], dtype="int16",
                             callback=callback, blocksize=1024) as stream:
            clock.latency_s = float(stream.latency)
            print(f"音声デバイスの遅延 {clock.latency_s * 1000:.0f} ms")
            st = run_sender(ser, xy, fps, clock, duration_s=duration_s, loop=loop, lead_s=lead_s,
                            get_offset_s=lambda: offset["s"], stop=stop, on_second=report)
            time.sleep(0.5)
        print("done:", st, f"/ 最終の offset = {offset['s'] * 1000:+.0f} ms")
    except KeyboardInterrupt:
        print(f"stopped / 最終の offset = {offset['s'] * 1000:+.0f} ms")
    finally:
        stop.set()
        ser.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="映像を ESP32 に送りながら、音声を PC で鳴らす")
    ap.add_argument("osa")
    ap.add_argument("--audio", required=True, help="16bit PCM の WAV")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--offset-ms", type=float, default=0.0, help="+ で映像が先に出る")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--reset-wait", type=float, default=2.0)
    args = ap.parse_args(argv)
    for p in (args.osa, args.audio):
        if not Path(p).exists():
            sys.exit(f"ファイルがありません: {p}")
    play_av(args.osa, args.audio, args.port, args.baud, args.offset_ms, args.loop, args.reset_wait)


if __name__ == "__main__":
    main()
