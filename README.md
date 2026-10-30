## v0.3.0 の再生手順

### 1. 動画を .osa に変換 および音楽の同時再生

`tools/` で、venv を有効にして実行します。`badapple.mp4` は `tools/` に置きます（Git には入れません）。

<>は省いて以下のコマンドを実行してください。
```powershell
cd tools

python -m osaconv <ファイル名>.mp4 -o <生成ファイル名>.osa --start <開始秒> --seconds <終了秒> --invert --epsilon 1.5 --min-length 40 --points 1000

python -m osaconv.stream <生成ファイル名>.osa --port <ポート番号> --baud 921600 --loop // 映像のみ再生

ffmpeg -ss <開始秒> -t <終了秒> -i <ファイル名>.mp4 -vn -ac 2 -ar 44100 -c:a pcm_s16le <生成ファイル名>.wav

python -m osaconv.play <生成ファイル名>.osa --audio <生成ファイル名>.wav --port <ポート番号> --baud 921600 // 同時再生

```
#### osaファイル生成コマンドオプション
| オプション | 意味 |
|---|---|
| `--start 33` | 変換を始める位置（秒） |
| `--seconds 35` | 変換する長さ（秒）。ESP32 のフラッシュに入る量の目安は 35 秒前後 |
| `--invert` | 白黒を反転する（白背景の動画で、画面の枠が出ないようにする） |
| `--epsilon 1.5` | 輪郭の点の間引きの強さ（小さいほど滑らか、点が増える） |
| `--min-length 40` | これより短い輪郭は捨てる |
| `--points 1000` | 1 フレームの点数 N |

変換結果は `python scripts/view_osa.py <ファイル名>.osa --count 12` で、PC 上で確認できます。

### 2. ESP32 に書き込む

1. Arduino IDE で `firmware/osa_stream.ino` を開く
2. ボード: `ESP32 Dev Module`
3. **Partition Scheme: `Huge APP (3MB No OTA/1MB SPIFFS)`**（これを選ばないと、データが入らない）
4. **シリアルモニタは閉じること**
5. - オシロには、**動く円**が出るはずです

### 3. 配線

| ESP32 | オシロスコープ |
|---|---|
| GPIO25 | CH1（X） |
| GPIO26 | CH2（Y） |
| GND | CH1 / CH2 のグラウンド |

オシロは XY モード、両チャンネルを DC カップリングにします。

### 4. 動画と音声のずれの調整

```powershell
cd tools
python scripts/make_sync_test.py
python -m osaconv.play sync_test.osa --audio sync_test.wav --port COM6 --loop
```
- 実行中に +10 や -10 と入力して Enter を押すと、映像のタイミングを 10ms ずつ動かせます（+ で映像が先に出る）。合ったら、終了時に表示される値を --offset-ms に渡します。
- 音声には、有線のスピーカーかヘッドホンを使ってください。Bluetooth は遅延が大きく、合わせにくいです。
- 全長は、full.osa と、ffmpeg -i badapple.mp4 ...（-ss と -t なし）で作った audio_full.wav を使います。


### 5. 通信に余裕があるかを測る

```powershell
python -m osaconv.stream <生成ファイル名>.osa --port <ポート番号> --baud 921600 --benchmark 10
```

時刻を待たずに、最高の速さで10秒送ります。**`(+N/s)` の N が、通信の限界**です。

| ボーレート | 理論上の限界（私の計算） |
|---|---|
| 921600 | 約 45 フレーム/秒 |
| 2000000 | 約 99 フレーム/秒 |

N が 30 を十分に超えれば、余裕があります。ぎりぎり（30〜35）だと、本番で途切れる可能性があります。2000000 を試すときは、**ESP32 の `BAUD` と、PC の `--baud` を両方**変えて、書き込み直してください。


## 結果の読み方

| 症状 | 意味・対処 |
|---|---|
| `crc` や `lost` が増え続ける | 通信が乱れています。ボーレートを下げる、短いケーブルに替える |
| `[PC] skipped` が増える | PC の送信が間に合っていません。他のアプリを閉じる |
| `ok` が 0 のまま、動く円しか出ない | ボーレートの不一致、シリアルモニタが開いている、のどちらかを確認する |
| 動画の途中で円に戻る | データが1秒以上途切れています |
| `tmo` が増える | 受信の途中で止まっています。ケーブルを確認する |


## 気をつけること

- **USB-シリアルチップの上限は、COM6 という名前だけでは分かりません。** デバイスマネージャーの「ポート (COM と LPT)」で、COM6 の名前を確認してください。一般的な仕様では、CP2102 は最大約 1Mbps、CH340 は約 2Mbps とされています。まず 921600 で試してください
- ポートを開いた瞬間に、ESP32 がリセットされることがあります。対策として、DTR / RTS を無効にして開き、2秒待っています（`--reset-wait`）
- `Serial.printf` による**デバッグ表示は、映像の通信と同じ線に混ざります**。状況は `STAT` の行としてだけ、返しています
