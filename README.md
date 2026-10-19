# Oscilloscope Art Player（ESP32 + SD + I2S Audio）

オシロスコープの XY モードに動画（Bad Apple など）を描画し、同時に音声を再生する装置です。
PC 側で動画を専用形式 `.osa` に変換し、SD カードに入れた ESP32 が単体でループ再生します。

- 目標: **2週間以内に Bad Apple（約3分40秒）を音付きで再生**。最大 8 分まで対応
- 体制: 2名（ファームウェア/ハード担当 と Python 変換担当）
- 2人の契約は **[docs/FORMAT.md](docs/FORMAT.md)（`.osa` 仕様）**。変更するときは必ず相談する

---

## 1. 全体の動作フロー

```
【PC / Python】
 動画(mp4) ──ffmpeg──> フレーム画像 + 音声(22.05kHz / 8bit / mono)
   フレーム → 二値化 → 輪郭抽出 → 一筆書きに接続 → N点に等間隔リサンプリング
   XY点列 + 音声 を 1フレームずつ交互に並べて video.osa に出力
   ※ preview.py で PC 上でも再生確認できる

        video.osa を SD カード（FAT32）にコピー

【ESP32 / ファームウェア】
 SDカード ──SPI──> Reader task（フレーム単位で読み出し）
                      ├─> XY task    ─> dac_continuous ─> GPIO25(X) / GPIO26(Y) ─> オシロ
                      └─> Audio task ─> I2S1 ─> MAX98357A ─> スピーカー
 最終フレームまで再生したら先頭に戻ってループ
```

## 2. 技術スタック

| 領域 | 採用 | 理由 |
|---|---|---|
| マイコン | ESP32（無印、DevKitC 系） | 内蔵 DAC 2ch があるのは無印のみ（S3/C3 は不可） |
| ビルド環境 | PlatformIO（pioarduino 版 espressif32）+ Arduino-ESP32 3.x | `dac_continuous` が使える。VS Code で Git 管理しやすい |
| 映像出力 | `dac_continuous`（DMA、2ch 交互） | CPU 負荷が低く、一定レートで出力できる |
| 音声出力 | 外付け I2S アンプ MAX98357A（I2S1 側） | 配線 3 本でノイズが少ない |
| ストレージ | microSD（SPI、FAT32、VSPI） | 約 40MB でも余裕。必要な読み出し速度は約 82KB/s |
| PC 側 | Python 3.11、numpy、opencv-python、scipy、ffmpeg（CLI） | 輪郭処理は情報が多い定番構成 |
| プレビュー | matplotlib または pygame | ハード無しで `.osa` を再生確認 |
| 共有 | GitHub（`main` + 機能ブランチ） | 2 人でのコンフリクト回避 |

## 3. データ形式 `.osa`（リトルエンディアン・固定長）

### ヘッダ（16 バイト）

| オフセット | 名前 | 型 | 値 |
|---|---|---|---|
| 0 | magic | char[4] | `"OSA1"` |
| 4 | version | u8 | 1 |
| 5 | fps | u8 | 30 |
| 6 | points_per_frame (N) | u16 | 1000 |
| 8 | audio_rate | u16 | 22050 |
| 10 | audio_per_frame | u16 | 735（= audio_rate ÷ fps） |
| 12 | frame_count | u32 | 総フレーム数 |

Python の struct では `"<4sBBHHHI"`（ちょうど 16 バイト）。

### フレーム i

```
オフセット = 16 + i × stride
stride     = 2N + audio_per_frame        （既定値: 2000 + 735 = 2735 バイト）

[ x0, y0, x1, y1, ... x(N-1), y(N-1) ]   各 u8（0〜255）、計 2N バイト
[ 音声サンプル × audio_per_frame ]        u8（無音 = 128）
```

- XY は**最初から x, y 交互**に並べる。ESP32 は DAC バッファにそのままコピーするだけでよい
- 固定長なので、シークとループは単純な掛け算で済む
- 8 分（14,400 フレーム）で約 39MB
- 時間の基準はハードウェアクロック。XY は N × fps = 30kHz、音声は 22,050Hz で、ソフトでの同期処理は不要
- 前提: `audio_rate ÷ fps` が整数になること。変更時はこの条件を守る

## 4. ディレクトリ構成

```
oscilloscope-art/
├─ README.md
├─ docs/
│  ├─ FORMAT.md          .osa 仕様（契約）
│  ├─ WIRING.md          配線図・ピンアサイン
│  └─ SCHEDULE.md
├─ tools/                【Python 担当】
│  ├─ pyproject.toml
│  ├─ osaconv/
│  │  ├─ __main__.py     CLI: python -m osaconv in.mp4 -o out.osa
│  │  ├─ extract.py      ffmpeg でフレーム・音声抽出
│  │  ├─ contour.py      二値化 → 輪郭抽出 → 簡略化
│  │  ├─ path.py         一筆書き接続・等間隔リサンプリング
│  │  ├─ pack.py         .osa 書き出し
│  │  └─ preview.py      .osa を PC 上で再生
│  ├─ make_test.py       テスト用 .osa 生成（円・リサジュー + サイン波）
│  └─ tests/
├─ firmware/             【ファームウェア担当】
│  ├─ platformio.ini
│  ├─ include/config.h   ピン・N・fps などの定数
│  └─ src/
│     ├─ main.cpp
│     ├─ sd_reader.cpp/.h   ヘッダ解析・フレーム読み出し
│     ├─ xy_out.cpp/.h      dac_continuous 制御
│     ├─ audio_out.cpp/.h   I2S 制御
│     └─ player.cpp/.h      3 タスクの連携・ループ処理
├─ samples/              小さい .osa のみコミット
└─ .gitignore            *.mp4 *.osa（samples/ は除く）
```

## 5. ハードウェア

### ピンアサイン

| 用途 | ピン |
|---|---|
| X 出力（DAC） | GPIO25 |
| Y 出力（DAC） | GPIO26 |
| SD（VSPI） | CS=5, SCK=18, MISO=19, MOSI=23 |
| I2S 音声（MAX98357A） | BCLK=27, LRC=32, DIN=33 |

### 接続メモ

- DAC 出力には直列に 100Ω〜1kΩ を入れてオシロへ接続し、GND を共通にする
- オシロは **XY モード・DC カップリング**。1V/div 前後から調整する
- DAC は 0〜約 3.3V の出力（8bit・256 段階）。画面の中心が合わない場合はオシロ側のポジションで調整する

## 6. 役割分担

| 担当 | 範囲 |
|---|---|
| **ファームウェア/ハード** | 配線、`firmware/` 全体、実機での画質調整、録画 |
| **Python 変換** | `tools/` 全体、輪郭品質の改善、`preview.py`、変換速度 |

境界は `.osa` ファイルだけです。お互いの実装を待たずに進められるよう、最初にテスト用 `.osa` を作ります。

## 7. 2週間スケジュール

| 期間 | ファームウェア/ハード | Python 変換 |
|---|---|---|
| Day 1–2 | 配線。DAC 連続出力で円とリサジューが出るか確認 | リポジトリ作成。`make_test.py` で**テスト用 .osa**を作る |
| Day 3–5 | SD から .osa を読んで XY 再生（無音） | Bad Apple の二値化 → 輪郭 → 一筆書き → .osa 出力 |
| Day 6–8 | I2S 音声を追加し、XY と同時再生 | リサンプリング改良、ちらつき対策、`preview.py` |
| Day 9–11 | ループ再生、バッファ（アンダーラン）調整 | 音声同梱、8 分クラスの変換速度確認 |
| Day 12–14 | 予備日（実機での画質調整、配線見直し、録画） | 同上 |

**マイルストーン**
1. M1（Day 2）: テスト .osa が PC プレビューで再生でき、実機で円が描ける
2. M2（Day 5）: Bad Apple が実機で無音再生できる
3. M3（Day 8）: 音声付きで再生できる
4. M4（Day 11）: 最後まで再生してループする
5. M5（Day 14）: 録画と最終調整

## 8. 開発ルール

- `main` は常に動く状態に保つ。作業は `feat/xxx` ブランチで行い、PR でマージする
- `.osa` の仕様変更は `docs/FORMAT.md` を更新する PR を先に出し、相手の承認を取る
- `*.mp4`、`*.osa` はコミットしない。共有が必要な動画データはクラウドストレージなどで渡す（`samples/` の小さい .osa のみ可）
- 定数（N、fps、ピン）は `firmware/include/config.h` と `.osa` ヘッダの 2 か所に分かれる。ファームはヘッダを読んで動作し、`config.h` の値は既定値として扱う

## 9. クイックスタート

### Python 側

```bash
cd tools
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
python make_test.py -o ../samples/test.osa          # テスト用データ
python -m osaconv.preview ../samples/test.osa       # PC 上で確認
python -m osaconv badapple.mp4 -o video.osa         # 本番変換
```

### ファームウェア側

```bash
cd firmware
pio run -t upload
pio device monitor
```

SD カードは FAT32 でフォーマットし、ルートに `video.osa` を置きます。

## 10. 先に潰しておくリスク

1. **DAC 連続出力の挙動（Day 1 で検証）**
   2ch 交互モードでのサンプルレートの意味（ペア単位か片側か）は実機で確認する。違った場合は設定値を 2 倍にするだけ。
2. **SD 読み出しの途切れ**
   DMA バッファを 2〜3 フレーム分持ち、Reader タスクを別コアに置く。
3. **輪郭のつなぎ線**
   Z チャンネルが無いので、輪郭間の移動線が見える。まず許容し、後で並び順の最適化（最近傍法 → 2-opt）で減らす。
4. **PlatformIO と Arduino-ESP32 3.x の組み合わせ**
   公式プラットフォームは 3.x 対応が遅れている。pioarduino 版を使い、環境構築は最初の 1 日以内に終わらせる。
5. **DAC の下限サンプルレート**
   連続出力には約 20kHz の下限がある。N × fps がこれ以上になるようにする（30fps なら N ≥ 700）。
6. **DAC 内蔵のため音声が別経路**
   内蔵 DAC 2ch は XY で埋まるので、音声は I2S アンプを使う。部品が間に合わない場合は PWM + RC ローパスで代替する。

## 11. 部品リスト

- ESP32 DevKitC（無印）
- microSD カードモジュール（SPI）と microSD カード
- MAX98357A I2S アンプ基板
- 小型スピーカー（4〜8Ω、3W 程度）
- 抵抗 100Ω〜1kΩ × 2、ブレッドボード、ジャンパ線
- BNC（またはワニ口）ケーブルでオシロ（XY モード対応）に接続

## 12. 将来の拡張（余裕があれば）

- 輪郭の並び順最適化によるつなぎ線の削減
- 複数ファイルの選択再生（ボタン操作）
- 外付け DAC（I2S の 16bit DAC など）で解像度アップ
- Z 入力のあるオシロでのブランキング対応
