# ハンズオン: 輪郭抽出（contour.py）を触って覚える

目的は「コードを書き上げること」より、**どの設定が何を変えるのかを体で覚える**ことです。
目安時間は **半日〜1日**。深掘りしすぎないこと（目標は v0.1.0）。

## 進め方のルール

1. **予想してから動かす。** 実験の前に「予想」欄へ一言書く。外れた所が一番学べる
2. **1回に1か所だけ変える。**
3. **見た目と数字の両方を見る。** 画面左上の `contours`（輪郭の本数）と `points`（総点数）を記録する
4. **わざと壊す。** エラーや崩れ方を知っておくと、後のバグ探しが楽になる
5. 分かったことは、自分の言葉で `docs/NOTES.md` に 1 行ずつ残す

## 準備

```bash
git switch main && git pull
git switch -c feat/contour
cd tools
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -v                 # test_contour.py が全部通れば準備OK
```

- 動画（Bad Apple）は `tools/` に置いてよい（`*.mp4` は git 管理しない設定）
- 今回の確認ツール: `tools/scripts/tune_contour.py`（スライダー付き）

---

## Step 1: スライダーで自由に遊ぶ（約 15 分）

```bash
python scripts/tune_contour.py badapple.mp4 --frame 1000
```

3 枚が並んで表示されます。**[元画像] [二値化後] [輪郭を重ねた画像]**。
スライダーを自由に動かして、何が起きるか眺めてください。ここでは予想も記録も不要です。

| 操作 | 内容 |
|---|---|
| `a` / `d`（または ← →） | 前後のフレーム |
| `p` | 今のパラメータを端末に表示 |
| `s` | 画面を画像として保存 |
| `q` | 終了 |

画面が大きすぎるときは `--width 1200` で小さくできます。
フレームを何枚か見て、**場面の違う 3 枚**を選び、番号を記録してください。

| 場面 | フレーム番号 | メモ |
|---|---|---|
| 人物が大きい場面 | | |
| 細かい（複雑な）場面 | | |
| ほぼ真っ黒 / 真っ白な場面 | | |

以降の実験は、この 3 枚で試します。

---

## Step 2: 最小コードを手で打つ（約 20 分）

**コピペせず、手で打ってください。** Python のインタラクティブ環境（`python` と入力）か、新しい `.py` ファイルで 1 行ずつ実行します。

```python
import cv2

cap = cv2.VideoCapture("badapple.mp4")
cap.set(cv2.CAP_PROP_POS_FRAMES, 1000)        # ← Step 1 で選んだフレーム番号
ok, frame = cap.read()
print(ok, frame.shape, frame.dtype)

gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
print(gray.shape, gray.dtype)

thresh, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
print("大津法が決めたしきい値:", thresh)

contours, hierarchy = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
print("輪郭の本数:", len(contours))
print("1 本目の shape:", contours[0].shape, contours[0].dtype)
```

**打ちながら答えを書き込んでください**（実行前に予想 → 実行後に実際の値）。

| 質問 | 予想 | 実際 |
|---|---|---|
| `frame.shape` は？ 3 つ目の数字は何を表す？ | | |
| `gray.shape` は？（`frame.shape` との違いは？） | | |
| 大津法が決めたしきい値は？ | | |
| `contours[0].shape` は？ 真ん中の `1` は何のため？ | | |
| `len(contours)` は、目で数えた本数と合う？ | | |

---

## Step 3: 実験（約 60〜90 分）

`tune_contour.py` を使い、**Step 1 の 3 枚それぞれ**で試します。
「予想」は、動かす**前**に書いてください。

### 実験 1: しきい値

大津法（スライダー 0）から、`threshold` を 64 → 127 → 200 と変える。

| 予想 | 結果（中央の二値画像、contours/points） | 気づき |
|---|---|---|
| | | |

観点: 白い面積はどう変わるか。輪郭の本数と総点数は？

### 実験 2: `invert`（白黒反転）

`invert` を ON / OFF する。

| 予想 | 結果 | 気づき |
|---|---|---|
| | | |

観点: **画面の枠（四角）が輪郭に出るのはどちらか。なぜか？**
ヒント: `findContours` は「白い部分」を物体として輪郭を探します。

### 実験 3: 輪郭の取り方 `external only`

ON（外側だけ）と OFF（全部）を比べる。

| 予想 | 結果 | 気づき |
|---|---|---|
| | | |

観点: 穴の空いた形（人物の内側の模様など）が、どう描かれるか。オシロで見るなら、どちらが良さそうか。

### 実験 4: `epsilon`（簡略化の強さ）

`epsilon x0.1` を 5 → 10 → 20 → 40（= epsilon 0.5 / 1 / 2 / 4）と変える。

| epsilon | 予想の総点数 | 実際の points | 見た目の変化 |
|---|---|---|---|
| 0.5 | | | |
| 1.0 | | | |
| 2.0 | | | |
| 4.0 | | | |

観点: **1 フレームの目標は 1,000 点前後。** 目標に収まるのはどの値か。そのとき見た目はどうなるか。
これが「画質」と「ESP32 に渡せる点数」のトレードオフです。

### 実験 5: `min_length`（小さな輪郭を捨てる）

`min_length` を 5 → 20 → 50 → 100 と変える。

| 予想 | 結果（本数の変化） | 気づき |
|---|---|---|
| | | |

観点: どのくらいから、必要な線まで消え始めるか。

### 実験 6: `blur`（ぼかし）

`blur` を 0 → 1 → 2 → 3 と変える（ぼかしの大きさは 3 → 5 → 7 ピクセル）。

| 予想 | 結果 | 気づき |
|---|---|---|
| | | |

観点: 輪郭の滑らかさと点数、細かい部分の消え方。

### 実験 7: 3 枚を比べる

自分で決めた「いちばん良さそうな設定」を、3 枚すべてに当てる。

| 場面 | その設定で見た目は良い？ | 問題点 |
|---|---|---|
| 人物が大きい | | |
| 細かい | | |
| ほぼ真っ黒 / 真っ白 | | |

最後に、`p` キーで設定を表示して記録しておく:

```
ContourParams(threshold=..., invert=..., blur_ksize=..., epsilon=..., min_length=..., retrieval=...)
```

---

## Step 4: わざと壊す（約 20 分）

Python で直接呼んで、壊れ方を見ておきます。（`tools/` で `python` を起動して実行）

```python
import numpy as np
from osaconv.contour import frame_to_contours, ContourParams

gray = np.zeros((100, 100), np.uint8)
```

| やること | 予想 | 実際 |
|---|---|---|
| `frame_to_contours(gray)`（真っ黒の画像） | | |
| `frame_to_contours(np.zeros((10, 10, 3), np.uint8))`（カラー画像） | | |
| `frame_to_contours(gray, ContourParams(blur_ksize=4))`（偶数のぼかし） | | |
| `ContourParams(epsilon=0)` でスライダーを試す（点数は？） | | |
| `ContourParams(threshold=255)` で実行すると何が起きる？ | | |

エラーメッセージは**全文を読む**習慣を付けてください。

---

## Step 5: コードを読む（約 20 分）

`tools/osaconv/contour.py` を開き、Step 3 の実験と対応づけます。

| 実験したもの | コードの場所 | 使っている OpenCV の関数 |
|---|---|---|
| threshold / invert | `_binarize` | `cv2.threshold` |
| blur | `_binarize` の前半 | `cv2.GaussianBlur` |
| external only | `_find_raw` | `cv2.findContours` の `mode` |
| epsilon | `_simplify` | `cv2.approxPolyDP` |
| min_length | `frame_to_contours` のループ内 | `cv2.arcLength` |
| 形の変換 | `_to_closed_xy` | numpy の `reshape` / `vstack` |

次の問いに、**コードを見ずに**答えられるか試してください。

1. `findContours` が返す輪郭の形は？ なぜ `(M, 1, 2)` を `(M, 2)` に直すのか？
2. `_to_closed_xy` で、最後に最初の点を足すのはなぜか？
3. `frame_to_contours` が `ValueError` を出すのはどんなとき？

---

## Step 6: 自力で書き直す（約 60 分）

1. `contour.py` を別名に退避する（例: `contour_ref.py`）
2. 次の仕様だけを見ながら、**白紙から**書く
   - 入力: `(H, W) uint8` のグレースケール、設定は `ContourParams`
   - 出力: `list[(M, 2) float32]`、閉じた輪郭、輪郭なしなら `[]`
3. `python -m pytest -v` が通るまで直す
4. `contour_ref.py` と見比べて、違う所とその理由を書き出す
5. 比較が終わったら、自分のコードか参考コードのどちらかを正式な `contour.py` にする

詰まったら、**エラーメッセージ全文**と、**どこまで試したか**を添えて AI に質問してください。

---

## Step 7: 記録とまとめ

- 分かったことを `docs/NOTES.md` に 1 行ずつ書く
- Step 3 の「いちばん良さそうな設定」を、`ContourParams` の既定値に反映するかを友人と相談する
- `feat/contour` を push して Pull Request を作る

### 完了チェック

- [ ] 3 枚の場面で、Step 3 の実験を一通り試した
- [ ] 自分の言葉で、`invert` が必要な理由を説明できる
- [ ] `epsilon` と総点数の関係を、数字で言える
- [ ] `python -m pytest -v` が通る
- [ ] `NOTES.md` に 5 行以上書いた