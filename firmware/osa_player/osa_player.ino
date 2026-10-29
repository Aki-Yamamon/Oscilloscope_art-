// osa_player.ino -- .osa（輪郭の座標データ）をオシロスコープに再生する   v0.1.0（映像のみ）
//
// 仕組み:
//   フラッシュに埋め込んだ osa_data.h（tools/scripts/osa2h.py で生成）を読み、
//   フレームごとの N 点を DAC25（X）と DAC26（Y）に順番に出力する。
//   どのフレームを出すかは「経過時間」で決める。1 フレームの表示時間（1/fps 秒）が終わるまで
//   同じフレームを何周も描き直す。描き直す回数は dacWrite の速さで自動的に決まり、
//   周回が多いほどオシロ上の線は明るく、ちらつきも少なくなる。
//   最後のフレームまで来たら先頭に戻る（ループ再生）。
//
// 配線: GPIO25 → (100Ω〜1kΩ) → オシロ CH1(X) / GPIO26 → (100Ω〜1kΩ) → オシロ CH2(Y) / GND 共通
//       オシロは XY モード、DC カップリング
//
// ビルド: Arduino IDE なら「ツール → Partition Scheme → Huge APP (3MB No OTA/1MB SPIFFS)」を選ぶ

#include <Arduino.h>
#include "esp_timer.h"
#include "osa_data.h"   // OSA_DATA[]（.osa の中身そのまま）と OSA_LEN

// ---- 調整用の設定 ----
constexpr uint8_t  PIN_X = 25;           // DAC1（オシロ CH1 = X）
constexpr uint8_t  PIN_Y = 26;           // DAC2（オシロ CH2 = Y）
constexpr uint32_t POINT_DELAY_US = 0;   // 1 点ごとの待ち（マイクロ秒）。0 で最速
constexpr bool     SERIAL_STATS = true;  // 1 秒ごとに状況をシリアルに出す（本番では false でもよい）

// ---- .osa のヘッダ（16 バイト）。仕様は docs/FORMAT.md ----
constexpr size_t HEADER_SIZE = 16;
static uint16_t g_fps = 0;       // フレームレート
static uint16_t g_n = 0;         // 1 フレームの点数 N
static uint32_t g_frames = 0;    // フレーム数
static size_t   g_stride = 0;    // 1 フレームのバイト数 = 2N + 音声バイト数
static int64_t  g_startUs = 0;   // 再生開始時刻（マイクロ秒）

static uint16_t rd16(const uint8_t* p) { return p[0] | (p[1] << 8); }
static uint32_t rd32(const uint8_t* p) {
  return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24);
}

// ヘッダを読んで、データが正しいか確認する。ダメなら理由を表示して false。
static bool parseHeader() {
  if (OSA_LEN < HEADER_SIZE || memcmp(OSA_DATA, "OSA1", 4) != 0) {
    Serial.println("ERROR: .osa の先頭が OSA1 ではありません");
    return false;
  }
  g_fps = OSA_DATA[5];
  g_n = rd16(OSA_DATA + 6);
  const uint16_t audioPerFrame = rd16(OSA_DATA + 10);
  g_frames = rd32(OSA_DATA + 12);
  g_stride = 2 * (size_t)g_n + audioPerFrame;   // 音声があっても、XY は各フレームの先頭にある

  if (g_fps == 0 || g_n < 2 || g_frames == 0) {
    Serial.println("ERROR: ヘッダの値が不正です");
    return false;
  }
  if (OSA_LEN != HEADER_SIZE + (size_t)g_frames * g_stride) {
    Serial.println("ERROR: ファイルサイズがヘッダと合いません");
    return false;
  }
  return true;
}

// 1 周ぶん（N 点）を出力する。xy は x0,y0,x1,y1,... の並び。
static inline void drawPass(const uint8_t* xy) {
  for (uint16_t i = 0; i < g_n; i++) {
    dacWrite(PIN_X, xy[2 * i]);
    dacWrite(PIN_Y, xy[2 * i + 1]);
    if (POINT_DELAY_US) delayMicroseconds(POINT_DELAY_US);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  if (!parseHeader()) {
    while (true) {                     // 異常なら止めて、メッセージを出し続ける
      Serial.println("データを確認してください（osa_data.h の作り直し）");
      delay(1000);
    }
  }
  Serial.printf("OSA: %u fps, N=%u, %lu frames (%.1f s)\n",
                g_fps, g_n, (unsigned long)g_frames, (double)g_frames / g_fps);
  dacWrite(PIN_X, 128);                // 画面中央にビームを置いてから始める
  dacWrite(PIN_Y, 128);
  g_startUs = esp_timer_get_time();
}

void loop() {
  // 今は何フレーム目か（経過時間から計算。ループのたびに先頭へ戻る）
  const uint64_t nowUs = (uint64_t)(esp_timer_get_time() - g_startUs);
  const uint64_t absFrame = nowUs * g_fps / 1000000ULL;
  const uint64_t endUs = (absFrame + 1) * 1000000ULL / g_fps;   // このフレームの表示を終える時刻
  const uint8_t* xy = OSA_DATA + HEADER_SIZE + (size_t)(absFrame % g_frames) * g_stride;

  static uint32_t passes = 0, shown = 0;
  do {
    drawPass(xy);
    passes++;
  } while ((uint64_t)(esp_timer_get_time() - g_startUs) < endUs);
  shown++;

  if (SERIAL_STATS) {
    static int64_t lastUs = 0;
    const int64_t t = esp_timer_get_time();
    if (t - lastUs >= 1000000) {
      Serial.printf("frames/s=%lu  passes/frame=%.1f  us/pass=%.0f\n",
                    (unsigned long)shown, (double)passes / shown, 1e6 / passes);
      passes = 0; shown = 0; lastUs = t;
    }
  }
}
