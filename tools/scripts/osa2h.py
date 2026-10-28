"""`.osa` を C のヘッダファイル（osa_data.h）に変換する。ESP32 のフラッシュに埋め込むため。

    python scripts/osa2h.py main.osa -o ../firmware/osa_player/osa_data.h

できた osa_data.h を、スケッチ（osa_player.ino）と同じフォルダに置いてビルドする。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osaconv.pack import read_osa   # 変換前に、.osa が壊れていないか確認するため

# huge_app パーティション（アプリ領域 3MB）で、コード分を引いたデータの目安
FLASH_BUDGET = 2_700_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("osa")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    raw = Path(args.osa).read_bytes()
    header, _, _ = read_osa(args.osa)         # 壊れていれば、ここで ValueError
    print(header)
    print(f"{len(raw):,} bytes  ({header.frame_count / header.fps:.1f} s)")
    if len(raw) > FLASH_BUDGET:
        print(f"警告: {FLASH_BUDGET:,} バイトを超えています。フラッシュに入らない可能性があります")

    per_line = 40
    lines = []
    for i in range(0, len(raw), per_line):
        lines.append(",".join(str(b) for b in raw[i:i + per_line]))

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("// 自動生成: tools/scripts/osa2h.py  （手で編集しないこと）\n")
        f.write(f"// 元ファイル: {Path(args.osa).name}\n")
        f.write("#pragma once\n#include <Arduino.h>\n#include <stddef.h>\n#include <stdint.h>\n\n")
        f.write(f"const size_t OSA_LEN = {len(raw)};\n")
        f.write("const uint8_t OSA_DATA[] PROGMEM = {\n")
        f.write(",\n".join(lines))
        f.write("\n};\n")
    print("saved:", args.out, f"({Path(args.out).stat().st_size / 1e6:.1f} MB のソース)")


if __name__ == "__main__":
    main()