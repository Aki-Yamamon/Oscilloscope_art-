"""PC から ESP32 へ、.osa のフレームをシリアル通信で送る（v0.2.0）。

    python -m osaconv.stream full.osa --port COM6 --baud 921600
    python -m osaconv.stream full.osa --port COM6 --baud 921600 --loop
    python -m osaconv.stream full.osa --port COM6 --baud 2000000 --benchmark 10

パケットの形式（リトルエンディアン）:
    A5 5A          同期バイト（パケットの先頭の目印）
    type  (1)      0x01 = XY のフレーム（0x02 は将来 XYZ 用に予約）
    seq   (4)      パケットの通し番号（送るたびに +1。欠落の検出に使う）
    len   (2)      本体のバイト数
    本体  (len)    x0,y0,x1,y1,...（各 u8）
    crc   (2)      type〜本体 の CRC-16/CCITT-FALSE（多項式 0x1021、初期値 0xFFFF）

時間の基準は PC。フレーム i を、開始から i/fps 秒の時刻に送る。遅れたら、遅れた分のフレームを
飛ばして、時刻を合わせる（音声を足したときに、映像がずれないようにするため）。
"""
from __future__ import annotations

import argparse
import binascii
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from osaconv.pack import read_osa

SYNC = b"\xA5\x5A"
TYPE_FRAME_XY = 0x01


def crc16(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE。ESP32 側（osa_stream.ino）と同じ計算。"""
    return binascii.crc_hqx(data, init)


def build_packet(ptype: int, seq: int, payload: bytes) -> bytes:
    """パケットを 1 つ作る。"""
    if len(payload) > 0xFFFF:
        raise ValueError("本体が大きすぎます")
    body = struct.pack("<BIH", ptype, seq & 0xFFFFFFFF, len(payload)) + payload
    return SYNC + body + struct.pack("<H", crc16(body))


@dataclass
class StreamStats:
    sent: int = 0          # 送ったパケット数
    skipped: int = 0       # 遅れて、飛ばしたフレーム数
    bytes_sent: int = 0
    max_late_ms: float = 0.0


def _sleep_until(due: float) -> None:
    """時刻 due（perf_counter）まで待つ。最後の 2ms は、正確さのために空回しする。"""
    while True:
        rem = due - time.perf_counter()
        if rem <= 0:
            return
        if rem > 0.003:
            time.sleep(rem - 0.002)


def stream_osa(ser, osa_path, loop: bool = False, start_frame: int = 0,
               benchmark_sec: float | None = None, on_second=None) -> StreamStats:
    """.osa を ser（write() を持つもの）に送る。

    benchmark_sec を指定すると、時刻を待たずに、最高の速さで、その秒数だけ送り続ける。
    """
    header, xy, _ = read_osa(osa_path)
    fps, total = header.fps, header.frame_count
    st = StreamStats()
    t0 = time.perf_counter() - start_frame / fps
    t_begin = time.perf_counter()
    last_report = t_begin
    i = start_frame                       # 次に送るフレーム（ループのときは total を超えて増える）
    seq = 0

    while True:
        now = time.perf_counter()
        if benchmark_sec is not None:
            if now - t_begin >= benchmark_sec:
                break
        else:
            if not loop and i >= total:
                break
            due = t0 + i / fps
            if due > now:
                _sleep_until(due)
            else:
                late = now - due
                st.max_late_ms = max(st.max_late_ms, late * 1000)
                target = int((now - t0) * fps)
                if target > i:            # 1 フレーム以上遅れた: 追いつくために飛ばす
                    st.skipped += target - i
                    i = target
                    if not loop and i >= total:
                        break

        pkt = build_packet(TYPE_FRAME_XY, seq, xy[i % total].tobytes())
        ser.write(pkt)
        st.sent += 1
        st.bytes_sent += len(pkt)
        seq += 1
        i += 1

        if on_second is not None and time.perf_counter() - last_report >= 1.0:
            last_report = time.perf_counter()
            on_second(st, i, total)
    return st


def _reader(ser, stop: threading.Event) -> None:
    """ESP32 が送ってくる文字（STAT 行など）を、画面に出す。"""
    buf = b""
    while not stop.is_set():
        try:
            data = ser.read(ser.in_waiting or 1)
        except Exception:
            return
        if not data:
            continue
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                print("  ESP32>", text)


def open_port(port: str, baud: int, reset_wait: float):
    import serial   # pyserial（pip install pyserial）
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.1
    ser.write_timeout = 2.0
    ser.dtr = False                       # ポートを開いた瞬間に ESP32 がリセットされるのを避ける
    ser.rts = False
    ser.open()
    time.sleep(reset_wait)
    ser.reset_input_buffer()
    return ser


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=".osa をシリアル通信で ESP32 に送る")
    ap.add_argument("osa")
    ap.add_argument("--port", required=True, help="例: COM6")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--loop", action="store_true", help="最後まで行ったら先頭に戻る")
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--benchmark", type=float, default=None, metavar="SEC",
                    help="時刻を待たずに最高の速さで SEC 秒送り、通信が追いつくかを調べる")
    ap.add_argument("--reset-wait", type=float, default=2.0, help="ポートを開いたあとに待つ秒数")
    args = ap.parse_args(argv)

    if not Path(args.osa).exists():
        sys.exit(f"ファイルがありません: {args.osa}")
    ser = open_port(args.port, args.baud, args.reset_wait)
    stop = threading.Event()
    threading.Thread(target=_reader, args=(ser, stop), daemon=True).start()

    def report(st: StreamStats, i: int, total: int) -> None:
        print(f"[PC] sent={st.sent} skipped={st.skipped} max_late={st.max_late_ms:.1f}ms "
              f"frame={i % total}/{total} {st.bytes_sent / 1e3:.0f}KB")

    try:
        st = stream_osa(ser, args.osa, loop=args.loop, start_frame=args.start_frame,
                        benchmark_sec=args.benchmark, on_second=report)
        time.sleep(1.2)                   # 最後の STAT 行を受け取るため
        print("done:", st)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        stop.set()
        ser.close()


if __name__ == "__main__":
    main()
