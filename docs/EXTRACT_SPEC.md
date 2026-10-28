# `extract.py` 仕様書

動画ファイルから「映像フレーム」と「音声」を取り出すモジュールの仕様です。
Python は初めてでも読めるよう、背景の説明と参考コードを多めに書いてあります。

| 項目 | 内容 |
|---|---|
| 担当 | 友人（Python 担当） |
| 目安期間 | Day 1–2（他のモジュールより先に使えるようにしたい） |
| ブランチ名 | `feat/extract` |
| ファイル | `tools/osaconv/extract.py` |
| テスト | `tools/tests/test_extract.py` |

---

## 1. 目的

このプロジェクトは、動画（Bad Apple など）をオシロスコープに描画して再生する装置です。
`extract.py` はその**最初の工程**で、動画から次の 2 つを取り出します。

```
 動画 (mp4)
   ├─ 映像 → 1 コマずつ、グレースケール画像（numpy 配列）として返す  → contour.py へ
   └─ 音声 → 22,050Hz / 8bit / モノラルの配列として返す            → pack.py へ
```

後続の処理（輪郭抽出など）が使いやすいよう、**形式を固定して返す**ことが役目です。
形式は 3 章以降の仕様に従ってください。

### このモジュールがやらないこと

- 輪郭の抽出（`contour.py` の担当）
- 画像のリサイズや 0〜255 への座標変換（`path.py` の担当）
- `.osa` ファイルへの書き出し（`pack.py` の担当）

画像は**元の解像度のまま**返します。

---

## 2. 環境構築

### 2.1 必要なもの

| ツール | バージョン | 確認コマンド |
|---|---|---|
| Python | 3.11 以上 | `python --version` |
| Git | 任意 | `git --version` |
| ffmpeg（ffprobe を含む） | 任意の最近のもの | `ffmpeg -version` / `ffprobe -version` |

**ffmpeg のインストール**（Python のパッケージではなく、別のプログラムです）

- Windows: `winget install Gyan.FFmpeg`（インストール後、ターミナルを開き直す）
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`

`ffmpeg -version` と `ffprobe -version` の両方がバージョンを表示すれば OK です。

### 2.2 リポジトリとブランチ

```bash
git clone <リポジトリURL>
cd oscilloscope-art
git switch main
git pull
git switch -c feat/extract       # 作業用ブランチを作って移動
```

- `main` に直接コミットしない。作業は `feat/extract` で行い、完了したら Pull Request を出す
- コミットメッセージの例: `extract: add get_video_info`

### 2.3 venv（仮想環境）と requirements.txt

venv は「このプロジェクト専用の Python 環境」です。他のプロジェクトのパッケージと混ざりません。

```bash
cd tools
python -m venv .venv

# 有効化（OS で異なる）
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows（コマンドプロンプト / PowerShell）

pip install --upgrade pip
pip install -r requirements.txt
```

有効化すると、ターミナルの行頭に `(.venv)` が付きます。毎回ターミナルを開くたびに有効化が必要です。

**`tools/requirements.txt`**

```
numpy>=1.26
opencv-python>=4.9
scipy>=1.11
matplotlib>=3.8
pytest>=8.0
```

`extract.py` 自体が使うのは numpy だけですが、他のモジュールと共通の環境にするため、全部入れておきます。

> 補足: 今のところ README のクイックスタートは `pip install -e .`（pyproject.toml 方式）になっています。
> 当面は `pip install -r requirements.txt` を正とし、後で README を合わせます。

### 2.4 ディレクトリ構成

```
oscilloscope-art/
├─ docs/
└─ tools/
   ├─ requirements.txt
   ├─ .venv/                 ← git 管理しない
   ├─ osaconv/
   │  ├─ __init__.py         ← 空ファイル（これがあると "パッケージ" として扱われる）
   │  └─ extract.py          ← ★ 今回作るファイル
   └─ tests/
      ├─ __init__.py         ← 空ファイル
      └─ test_extract.py     ← ★ 今回作るテスト
```

`.gitignore` に次の行があるか確認してください（無ければ追加）。

```
.venv/
__pycache__/
*.mp4
*.osa
```

**動画ファイル（mp4）は絶対にコミットしないでください。** サイズが大きく、Git が重くなります。

---

## 3. 共通の約束事（定数）

`extract.py` の先頭に次の定数を定義します。他のモジュールも使うので、名前は変えないでください。

```python
DEFAULT_FPS = 30            # 出力フレームレート
DEFAULT_AUDIO_RATE = 22050  # 音声サンプリングレート（Hz）
AUDIO_SILENCE = 128         # 8bit 音声の無音の値（0〜255 の中央）
```

---

## 4. 作る関数・クラス一覧

| 名前 | 種類 | 役割 |
|---|---|---|
| `VideoInfo` | dataclass | 動画の情報（幅・高さ・fps・長さ・音声の有無） |
| `get_video_info()` | 関数 | ffprobe で動画の情報を取得 |
| `iter_frames()` | 関数（ジェネレータ） | グレースケール画像を 1 枚ずつ返す |
| `extract_audio()` | 関数 | 音声を 8bit の配列で返す |
| `calc_audio_per_frame()` | 関数 | 1 フレームあたりの音声サンプル数を計算 |
| `fit_audio_to_frames()` | 関数 | 音声の長さをフレーム数にそろえる |

内部用の補助関数 `_require_tool()` も作ります（5.1 参照）。

---

## 5. 関数の仕様

### 5.1 `_require_tool(name)`（内部用）

ffmpeg / ffprobe がインストールされているか確認し、無ければ分かりやすいエラーを出します。

```python
def _require_tool(name: str) -> None:
    """name（"ffmpeg" や "ffprobe"）が PATH に無ければ RuntimeError を出す。"""
```

- ヒント: 標準ライブラリの `shutil.which("ffmpeg")` を使います。見つからないと `None` を返します。
- エラーメッセージ例: `"ffmpeg が見つかりません。README の環境構築を確認してください"`
- 関数名の先頭の `_` は「このファイルの内部用」という Python の慣習です。

---

### 5.2 `VideoInfo` と `get_video_info()`

#### `VideoInfo`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class VideoInfo:
    width: int          # 映像の幅（ピクセル）
    height: int         # 映像の高さ（ピクセル）
    fps: float          # 元動画のフレームレート（例: 29.97）
    duration_sec: float # 動画の長さ（秒）
    has_audio: bool     # 音声トラックがあるか
```

`@dataclass` は「データをまとめるだけのクラス」を簡単に書く仕組みです（C の struct に近いイメージ）。
`frozen=True` は「作ったあとに値を書き換えられない」という指定です。

#### `get_video_info`

```python
def get_video_info(video_path: str | Path) -> VideoInfo:
    """動画の情報を ffprobe で取得する。"""
```

| 引数 | 型 | 説明 |
|---|---|---|
| `video_path` | `str` または `Path` | 動画ファイルのパス |

| 戻り値 | 説明 |
|---|---|
| `VideoInfo` | 上記のとおり |

| 例外 | 条件 |
|---|---|
| `FileNotFoundError` | ファイルが存在しない |
| `RuntimeError` | ffprobe が無い、または映像ストリームが無い |

**実装の手順**

1. `Path(video_path)` に変換し、`.exists()` で存在確認する
2. `_require_tool("ffprobe")` を呼ぶ
3. 次のコマンドを `subprocess.run` で実行し、標準出力を JSON として読む

```bash
ffprobe -v error -print_format json -show_streams -show_format <動画ファイル>
```

4. JSON の `streams`（配列）から、`codec_type` が `"video"` の最初の要素を探す。そこから `width`、`height`、`r_frame_rate` を取る
5. `r_frame_rate` は `"30000/1001"` のような**分数の文字列**。`fractions.Fraction("30000/1001")` で数値に変換し、`float()` にする
6. 長さは `format` の `duration`（**文字列**）を `float()` にして使う
7. `codec_type` が `"audio"` のストリームが 1 つでもあれば `has_audio=True`

**動作確認用の手動コマンド:** まず自分の端末で上の ffprobe コマンドを実行して、JSON がどんな形か目で見てください。それを見ながら書くのが一番早いです。

---

### 5.3 `iter_frames()`

動画のフレームを、**1 枚ずつ**グレースケール画像として返します。

```python
def iter_frames(
    video_path: str | Path,
    fps: int = DEFAULT_FPS,
    start_sec: float = 0.0,
    max_frames: int | None = None,
) -> Iterator[np.ndarray]:
    """グレースケールのフレームを 1 枚ずつ返す（ジェネレータ）。"""
```

| 引数 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `video_path` | `str` / `Path` | （必須） | 動画ファイルのパス |
| `fps` | `int` | `30` | 出力のフレームレート。元動画と違う場合は ffmpeg が間引き / 複製してそろえる |
| `start_sec` | `float` | `0.0` | 読み始める位置（秒）。動作確認で途中から試すときに使う |
| `max_frames` | `int` または `None` | `None` | 最大で何枚返すか。`None` なら最後まで |

| 戻り値（1 回の `yield` あたり） | 説明 |
|---|---|
| `np.ndarray`、shape `(height, width)`、dtype `uint8` | グレースケール画像。値は 0（黒）〜 255（白）。**書き込み可能**で、メモリ上で連続していること |

`np.ndarray` の shape は `(行数, 列数)` = `(高さ, 幅)` の順です。`(幅, 高さ)` ではありません。

| 例外 | 条件 |
|---|---|
| `FileNotFoundError` / `RuntimeError` | `get_video_info()` と同じ |

> 注意: ジェネレータ関数なので、エラーは**関数を呼んだ時ではなく、最初に値を取り出した時**に出ます。これは Python の仕様です。

#### ジェネレータとは（初心者向け）

`return` の代わりに `yield` を使うと、「1 つ返して、いったん止まり、次を求められたら続きから再開する」関数になります。

```python
for frame in iter_frames("badapple.mp4"):
    ...   # 1 枚ずつ取り出して処理できる
```

8 分の動画は約 14,400 枚です。全部をリストに入れるとメモリを使い切るため、**ジェネレータで 1 枚ずつ**返すのがこの関数の最重要ポイントです。

#### 使うコマンド

```bash
ffmpeg -loglevel error -ss <開始秒> -i <動画> -an -vf fps=<fps> -pix_fmt gray -f rawvideo -
```

| オプション | 意味 |
|---|---|
| `-loglevel error` | エラー以外のログを出さない |
| `-ss <秒>` | 開始位置（`-i` の**前**に置く） |
| `-an` | 音声は不要 |
| `-vf fps=30` | フレームレートを 30 にそろえる |
| `-pix_fmt gray` | 1 ピクセル 1 バイトのグレースケール |
| `-f rawvideo` | 圧縮なしの生データで出力 |
| `-` （最後） | **標準出力**に出す（ファイルに書かない） |

出力は「1 コマ目の全ピクセル、2 コマ目の全ピクセル、…」と続くだけのバイト列です。1 コマ分のバイト数は `width * height` なので、それずつ読めば 1 枚になります。幅と高さは `get_video_info()` で先に調べておきます。

#### 参考実装

ここが一番難しいので、動く参考コードを載せます。自分で書き直しても構いません。

```python
import subprocess
import numpy as np

def iter_frames(video_path, fps=DEFAULT_FPS, start_sec=0.0, max_frames=None):
    _require_tool("ffmpeg")
    info = get_video_info(video_path)            # ここで存在確認もされる
    w, h = info.width, info.height
    frame_bytes = w * h

    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-ss", str(start_sec), "-i", str(video_path),
        "-an", "-vf", f"fps={fps}",
        "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        count = 0
        while max_frames is None or count < max_frames:
            buf = proc.stdout.read(frame_bytes)   # 1 コマ分を読む
            if len(buf) < frame_bytes:            # 足りない = 動画の終わり
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w).copy()
            yield frame
            count += 1
    finally:
        proc.kill()      # 途中で止めた場合も ffmpeg を必ず終了させる
        proc.wait()
```

**ポイント解説**

- `subprocess.Popen(...)`: ffmpeg を起動して、出力を受け取り続ける
- `np.frombuffer(...)`: バイト列を numpy 配列にする。そのままだと**読み取り専用**なので、`.copy()` で書き込み可能にする
- `try ... finally`: ループを途中で抜けても、必ず `finally` の中身が実行される。ffmpeg を止め忘れないために必要
- `stderr=subprocess.DEVNULL`: ffmpeg のエラー出力を捨てる設定。**捨てないと、出力が溜まって止まる**ことがあるため（9 章参照）

---

### 5.4 `extract_audio()`

動画から音声を取り出し、8bit・モノラルの配列で返します。

```python
def extract_audio(
    video_path: str | Path,
    rate: int = DEFAULT_AUDIO_RATE,
    start_sec: float = 0.0,
    duration_sec: float | None = None,
) -> np.ndarray:
    """音声を 8bit モノラルの配列で返す。"""
```

| 引数 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `video_path` | `str` / `Path` | （必須） | 動画ファイルのパス |
| `rate` | `int` | `22050` | サンプリングレート（Hz） |
| `start_sec` | `float` | `0.0` | 読み始める位置（秒）。`iter_frames` と同じ値を使う |
| `duration_sec` | `float` または `None` | `None` | 取り出す長さ（秒）。`None` なら最後まで |

| 戻り値 | 説明 |
|---|---|
| `np.ndarray`、shape `(S,)`、dtype `uint8` | `S` = サンプル数（約 `秒数 × rate`）。**無音が 128**、波の山が 255 側、谷が 0 側 |

- **音声トラックが無い動画**: エラーにせず、**長さ 0 の配列**（`np.empty(0, dtype=np.uint8)`）を返す。判定は `get_video_info().has_audio` で行う
- 8 分の音声でも約 10MB なので、**全部をメモリに読んで OK**（映像と違ってジェネレータは不要）

#### 使うコマンド

```bash
ffmpeg -loglevel error -ss <開始秒> -i <動画> -vn -ac 1 -ar 22050 -f u8 [-t <長さ>] -
```

| オプション | 意味 |
|---|---|
| `-vn` | 映像は不要 |
| `-ac 1` | モノラルにする |
| `-ar 22050` | サンプリングレートを 22,050Hz にする |
| `-f u8` | **符号なし 8bit**（`.osa` の仕様と同じ。無音 = 128） |
| `-t <秒>` | 出力する長さ（`-i` の**後**に置く） |

#### 参考実装

```python
def extract_audio(video_path, rate=DEFAULT_AUDIO_RATE, start_sec=0.0, duration_sec=None):
    _require_tool("ffmpeg")
    info = get_video_info(video_path)
    if not info.has_audio:
        return np.empty(0, dtype=np.uint8)

    cmd = ["ffmpeg", "-loglevel", "error",
           "-ss", str(start_sec), "-i", str(video_path),
           "-vn", "-ac", "1", "-ar", str(rate), "-f", "u8"]
    if duration_sec is not None:
        cmd += ["-t", str(duration_sec)]
    cmd += ["-"]

    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).copy()
```

---

### 5.5 `calc_audio_per_frame()`

1 フレームあたりの音声サンプル数を計算します。

```python
def calc_audio_per_frame(rate: int, fps: int) -> int:
    """rate ÷ fps を返す。割り切れない場合は ValueError。"""
```

| 引数 | 型 | 説明 |
|---|---|---|
| `rate` | `int` | 音声のサンプリングレート（例: 22050） |
| `fps` | `int` | フレームレート（例: 30） |

| 戻り値 | 例 |
|---|---|
| `int` | `calc_audio_per_frame(22050, 30)` → `735` |

- 割り切れない場合（例: 22050 と 25 以外の組み合わせ）は `ValueError` を出す。割り算の**商だけが欲しい**ので `//`（整数除算）を使い、余りの確認には `%` を使う
- 割り切れる必要がある理由: `.osa` は 1 フレームの音声サンプル数が**固定**だから（`docs/FORMAT.md` 参照）

---

### 5.6 `fit_audio_to_frames()`

音声の長さを「フレーム数 × 1 フレームあたりのサンプル数」にぴったりそろえて、フレームごとに切り分けた 2 次元配列にして返します。

```python
def fit_audio_to_frames(
    audio: np.ndarray,
    frame_count: int,
    audio_per_frame: int,
) -> np.ndarray:
    """音声を (frame_count, audio_per_frame) の配列にそろえる。"""
```

| 引数 | 型 | 説明 |
|---|---|---|
| `audio` | `np.ndarray`、shape `(S,)`、dtype `uint8` | `extract_audio()` の戻り値 |
| `frame_count` | `int` | 映像のフレーム数 |
| `audio_per_frame` | `int` | 1 フレームあたりのサンプル数（735 など） |

| 戻り値 | 説明 |
|---|---|
| `np.ndarray`、shape `(frame_count, audio_per_frame)`、dtype `uint8` | `result[i]` が i 番目のフレームに対応する音声 |

**そろえ方**

- 必要な総サンプル数 `total = frame_count * audio_per_frame`
- `len(audio) >= total` なら、先頭の `total` 個だけ使う（余りは捨てる）
- `len(audio) < total` なら、足りない分を **`AUDIO_SILENCE`（128）で埋める**
- 最後に `.reshape(frame_count, audio_per_frame)` で 2 次元にする
- `audio` が長さ 0（音声なし）でも、全部が 128 の配列が返ること

使うと便利な numpy の関数: `np.full()`、`np.concatenate()`、スライス `audio[:total]`

---

## 6. 他のモジュールからの使われ方

最終的に `__main__.py` から次のように呼ばれる予定です。**この形で使えるように**してください。

```python
from osaconv.extract import (
    get_video_info, iter_frames, extract_audio,
    calc_audio_per_frame, fit_audio_to_frames,
    DEFAULT_FPS, DEFAULT_AUDIO_RATE,
)

info = get_video_info("badapple.mp4")
apf = calc_audio_per_frame(DEFAULT_AUDIO_RATE, DEFAULT_FPS)       # 735
audio = extract_audio("badapple.mp4", DEFAULT_AUDIO_RATE)

frame_count = 0
for gray in iter_frames("badapple.mp4", DEFAULT_FPS):
    ...                         # contour.py → path.py → pack.py へ
    frame_count += 1

audio2d = fit_audio_to_frames(audio, frame_count, apf)             # audio2d[i] が i 番目の音声
```

---

## 7. テスト仕様

`pytest` で自動テストを書きます。テスト用の動画は**テストの中で ffmpeg を使って生成**するので、mp4 をリポジトリに入れる必要はありません。

### 7.1 テスト用動画の作り方

ffmpeg には、テスト用の映像（`testsrc`）と音（`sine`）を自分で作る機能があります。

```bash
ffmpeg -y -loglevel error \
  -f lavfi -i testsrc=duration=3:size=320x240:rate=30 \
  -f lavfi -i sine=frequency=440:duration=3 \
  -pix_fmt yuv420p -shortest sample.mp4
```

3 秒・320×240・30fps の映像と、440Hz のサイン波音声ができます。

### 7.2 テストコードの骨組み

```python
# tests/test_extract.py
import subprocess
import numpy as np
import pytest
from osaconv.extract import *   # 実際は必要なものだけ import するのが望ましい

@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """テスト用動画を 1 回だけ作る。"""
    path = tmp_path_factory.mktemp("data") / "sample.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
           "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path
```

`fixture` は「テストの前準備」をまとめる pytest の仕組みです。テスト関数の引数に `sample_video` と書くだけで、作った動画のパスが渡されます。

### 7.3 テスト項目（最低限）

| テスト名の例 | 確認すること |
|---|---|
| `test_get_video_info` | 幅=320、高さ=240、fps≒30、長さ≒3 秒、`has_audio=True` |
| `test_get_video_info_missing_file` | 存在しないパスで `FileNotFoundError` |
| `test_iter_frames_shape_dtype` | 1 枚目の shape が `(240, 320)`、dtype が `uint8` |
| `test_iter_frames_count` | 全フレーム数が 89〜91（3 秒 × 30fps = 90 付近） |
| `test_iter_frames_max_frames` | `max_frames=10` で 10 枚だけ返る |
| `test_iter_frames_writable` | 返った配列に代入できる（`frame[0, 0] = 0` が通る） |
| `test_extract_audio` | dtype が `uint8`、長さが 66,150（= 3 × 22050）付近（±2,000 まで許容）、全部が 128 ではない（`audio.std() > 0`） |
| `test_extract_audio_no_audio_track` | 音声なしの動画（`-an` で別途作る）で、長さ 0 の配列 |
| `test_calc_audio_per_frame` | `(22050, 30)` → `735`、`(22050, 25)` は `ValueError` |
| `test_fit_audio_to_frames_pad` | 短い音声が 128 で埋められ、shape が `(frame_count, apf)` |
| `test_fit_audio_to_frames_cut` | 長い音声が切り詰められ、shape が `(frame_count, apf)` |

### 7.4 テストの実行

`tools/` ディレクトリで、venv を有効化した状態で実行します。

```bash
python -m pytest -v
```

`python -m pytest` と書くのは、`osaconv` パッケージを正しく見つけさせるためです（`pytest` だけだと import に失敗することがあります）。

---

## 8. 動作確認（本物の動画で）

`extract.py` の末尾に、次のような確認用の処理を付けてください。

```python
if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    info = get_video_info(path)
    print(info)
    n = sum(1 for _ in iter_frames(path, max_frames=60))
    print("frames:", n)
    audio = extract_audio(path, duration_sec=2.0)
    print("audio samples:", len(audio), "min/max:", audio.min(), audio.max())
```

実行（`tools/` で）:

```bash
python -m osaconv.extract path/to/badapple.mp4
```

期待する結果:

- `VideoInfo(...)` に、動画の解像度・fps・長さが正しく表示される
- `frames: 60`
- `audio samples:` が約 44,100（2 秒 × 22,050）で、`min/max` が 128 から離れた値になる

さらに、**目で確認**もしてください。最初の 1 枚を画像として表示します。

```python
import matplotlib.pyplot as plt
frame = next(iter_frames(path, start_sec=60))
plt.imshow(frame, cmap="gray")
plt.show()
```

Bad Apple の人物のシルエットが、白黒で表示されれば成功です。

---

## 9. ハマりやすいポイント

| 症状 | 原因と対策 |
|---|---|
| `FileNotFoundError: 'ffmpeg'` | ffmpeg が PATH に無い。インストール後、**ターミナルを開き直す** |
| 画像が斜めにずれる、縞模様になる | 読み込むバイト数の計算ミス（`width * height`）。shape が `(h, w)` の順か確認 |
| 動画の後半で止まる（ハングする） | ffmpeg の `stderr` を `PIPE` にして読んでいない。`DEVNULL` にする |
| 実行後に ffmpeg が裏で動き続ける | ジェネレータを途中で止めた時の後片付け漏れ。`try ... finally` で `kill()` する |
| `ValueError: ... read-only` | `np.frombuffer` の結果をそのまま使った。`.copy()` を付ける |
| 音がザーッと鳴る / 全部 128 になる | `-f u8` の指定漏れ、またはモノラル化（`-ac 1`）の漏れ |
| 映像と音声の長さが数フレームずれる | 正常。`fit_audio_to_frames()` で吸収する |
| `pytest` で `ModuleNotFoundError: osaconv` | `tools/` ディレクトリで `python -m pytest` を実行しているか確認。`osaconv/__init__.py` があるか確認 |
| `str \| Path` の書き方でエラー | Python 3.10 以前を使っている。3.11 以上にする |

---

## 10. Python 初心者向けメモ

他の言語の経験がある前提で、この仕様書に出てくる Python 特有の点をまとめます。

- **型ヒント**（`def f(x: int) -> str:`）は説明用の注釈で、実行時には強制されません。ただし読みやすさのために必ず書きます
- **`str | Path`** は「文字列または Path のどちらでもよい」という意味です
- **`Path`**（`from pathlib import Path`）は、ファイルパスを扱う標準のクラスです。`Path("a") / "b"` でパスを連結できます
- **スライス**: `a[:10]` は先頭 10 個、`a[-3:]` は末尾 3 個
- **numpy**: 配列を高速に扱うライブラリです。`array.shape`（形）と `array.dtype`（要素の型）をよく確認します
- **`with` 文 / `try ... finally`**: 後片付けを確実に行うための仕組みです（C++ の RAII や、他言語の `finally` と同じ考え方）
- **`__init__.py`**: ディレクトリを Python の「パッケージ」として扱うための目印です。空ファイルでよい

### AI に質問するときのヒント

- 「ffprobe の JSON 出力から、映像ストリームの幅と高さを取り出すコードを書いて」のように、入力と出力を具体的に書く
- 動いたコードは、**1 行ずつ意味を説明してもらう**
- エラーが出たら、エラーメッセージを**全文**貼って質問する
- 詰まったら、30 分以上悩む前に相談する（この共同制作者に聞いてOK）

---

## 11. 完了条件と提出方法

### 完了条件

- [ ] 4 章の関数・クラスがすべて仕様どおりに実装されている
- [ ] `python -m pytest -v` が全部通る
- [ ] 実際の Bad Apple で 8 章の動作確認ができ、1 枚目が白黒のシルエットとして表示される
- [ ] 関数すべてに docstring（`"""..."""` の説明文）がある
- [ ] mp4 / `.venv` がコミットに含まれていない

### 提出方法

```bash
git add tools/osaconv/extract.py tools/tests/test_extract.py tools/requirements.txt
git commit -m "extract: implement frame and audio extraction"
git push -u origin feat/extract
```

その後、GitHub で `feat/extract` → `main` の Pull Request を作成し、レビューを依頼してください。

### 仕様を変えたくなったとき

引数や戻り値の形式は、他のモジュールが依存します。**変更が必要になったら、実装する前に相談**してください。
