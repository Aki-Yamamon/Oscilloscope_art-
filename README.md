## v0.1.0 の再生手順（映像のみ・約35秒）

### 1. 動画を .osa に変換する

`tools/` で、venv を有効にして実行します。`badapple.mp4` は `tools/` に置きます（Git には入れません）。

```powershell
cd tools
python -m osaconv badapple.mp4 -o main.osa --start 33 --seconds 35 --invert --epsilon 1.5 --min-length 40 --points 1000
```

| オプション | 意味 |
|---|---|
| `--start 33` | 変換を始める位置（秒） |
| `--seconds 35` | 変換する長さ（秒）。ESP32 のフラッシュに入る量の目安は 35 秒前後 |
| `--invert` | 白黒を反転する（白背景の動画で、画面の枠が出ないようにする） |
| `--epsilon 1.5` | 輪郭の点の間引きの強さ（小さいほど滑らか、点が増える） |
| `--min-length 40` | これより短い輪郭は捨てる |
| `--points 1000` | 1 フレームの点数 N |

変換結果は `python scripts/view_osa.py main.osa --count 12` で、PC 上で確認できます。

### 2. ESP32 に埋め込むヘッダを作る

```powershell
python scripts/osa2h.py main.osa -o ../firmware/osa_player/osa_data.h
```

`osa_data.h` は自動生成のファイル（約 8MB）で、Git には入れません。

### 3. ESP32 に書き込む

1. Arduino IDE で `firmware/osa_player/osa_player.ino` を開く
2. ボード: `ESP32 Dev Module`
3. **Partition Scheme: `Huge APP (3MB No OTA/1MB SPIFFS)`**（これを選ばないと、データが入らない）
4. 書き込み後、シリアルモニタ（115200 bps）で再生状況を確認できる

### 4. 配線

| ESP32 | オシロスコープ |
|---|---|
| GPIO25 | CH1（X） |
| GPIO26 | CH2（Y） |
| GND | CH1 / CH2 のグラウンド |

オシロは XY モード、両チャンネルを DC カップリングにします。

### 既知の問題

- 表示が傾く場合は、`ROTATE_DEG` と `ROTATE_SCALE` で補正できます。`firmware/xy_test/xy_test.ino` で値を確認します
- 全長（約 3 分 40 秒）は、フラッシュに入りません。SPI の SD モジュールを使う `firmware/osa_player_sd/` が必要です
- 音声は未実装です