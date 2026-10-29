// osa_stream.ino -- PC からシリアル通信で届いた点列を、オシロスコープに描く   （v0.2.0・映像のみ）
//
// 仕組み:
//   コア 0（受信タスク）: シリアルからパケットを受け取り、CRC を確かめ、正しければ「最新のフレーム」にする
//   コア 1（loop）      : 最新のフレームを、次のフレームが届くまで描き続ける
//   PC が一定の間隔（1/fps 秒）でフレームを送るので、動画として再生される。
//   データが 1 秒以上届かないときは、動く円（待機パターン）を描く。
//   ※ CRT のオシロでは、ビームを止めたまま放置すると画面が焼けるので、待機中も必ず動かす。
//
// パケット形式（リトルエンディアン）は tools/osaconv/stream.py の冒頭を参照
//   A5 5A | type(1) | seq(4) | len(2) | 本体(len) | crc(2)   ※ crc は type〜本体 の CRC-16/CCITT-FALSE
//
// 注意:
//   ・このスケッチは、USB のシリアルを映像データの通信に使う。Arduino IDE のシリアルモニタは閉じること
//   ・PC 側の --baud と、下の BAUD を、必ず同じにする
//   ・状況は、1 秒ごとに "STAT ..." の行で PC に送り返す（PC のプログラムが画面に出す）
//
// 配線・オシロの設定は osa_player.ino と同じ（GPIO25 → X、GPIO26 → Y、GND 共通）

#include <Arduino.h>
#include <math.h>

// ---- 調整用の設定 ----
constexpr uint8_t  PIN_X = 25;
constexpr uint8_t  PIN_Y = 26;
constexpr uint32_t BAUD = 921600;           // まず 921600。余裕が無ければ 1500000 / 2000000（PC 側も合わせる）
constexpr size_t   RX_BUFFER_BYTES = 16384; // 受信バッファ（既定の 256 バイトでは、すぐあふれる）
constexpr uint16_t MAX_PAYLOAD = 4096;      // 1 フレームの本体の最大バイト数（= 最大 2048 点）
constexpr uint32_t IDLE_TIMEOUT_MS = 1000;  // この時間、フレームが届かなければ待機パターンに切り替える
constexpr uint32_t POINT_DELAY_US = 0;      // 1 点ごとの待ち（マイクロ秒）。0 で最速

constexpr uint8_t SYNC0 = 0xA5, SYNC1 = 0x5A;
constexpr uint8_t TYPE_FRAME_XY = 0x01;

// receivePacket() の戻り値
//   ※ enum を戻り値の型にすると、Arduino IDE が自動で作る関数の宣言より後に型が現れて、
//      コンパイルエラーになる。そのため int と定数にしている。
constexpr int RX_NONE = 0;   // データがまだ届いていない
constexpr int RX_OK = 1;     // 正しいフレームを受け取った
constexpr int RX_BAD = 2;    // 壊れていた・形式が違った（捨てた）

// ---- 受け取ったフレームの置き場（3 面）----
// 受信側は「最新（g_front）でも、描画中（g_busy）でもない面」にだけ書く。
// 描画側は「最新の面」を描画中にする。→ 描いている最中のデータが書き換わることは無い。
static uint8_t  g_buf[3][MAX_PAYLOAD];
static uint16_t g_count[3];                 // 各面の点数 N
static uint8_t  g_front = 0;
static uint8_t  g_busy = 0xFF;
static bool     g_hasFrame = false;
static uint32_t g_lastRxMs = 0;
static portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;

// ---- 統計 ----
struct Stats { uint32_t ok, crc, badLen, timeouts, lost, skipped; };
static Stats g_st = {};
static volatile uint32_t g_passes = 0;

static uint16_t rd16(const uint8_t* p) { return p[0] | (p[1] << 8); }
static uint32_t rd32(const uint8_t* p) {
  return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24);
}

// CRC-16/CCITT-FALSE（多項式 0x1021、初期値 0xFFFF）。PC 側の binascii.crc_hqx と同じ結果になる
static uint16_t crcUpdate(uint16_t crc, const uint8_t* d, size_t n) {
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (int b = 0; b < 8; b++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}

static int pickFreeSlot() {
  int slot = 0;
  portENTER_CRITICAL(&g_mux);
  for (int i = 0; i < 3; i++) {
    if (i != g_front && i != g_busy) { slot = i; break; }
  }
  portEXIT_CRITICAL(&g_mux);
  return slot;
}


// パケットを 1 つ受け取ろうとする。
//   RX_NONE: データがまだ届いていない（少し待ってから、もう一度呼ぶ）
//   RX_OK  : 正しいフレームを受け取り、最新のフレームにした
//   RX_BAD : 壊れていた・形式が違った（捨てた。次の同期バイトを探す）
static int receivePacket() {
  static uint8_t sync = 0;                       // 同期バイトの探索状態（0 = 何も見つかっていない）
  while (sync < 2) {
    const int b = Serial.read();
    if (b < 0) return RX_NONE;
    if (sync == 0) {
      if (b == SYNC0) sync = 1; else g_st.skipped++;
    } else {
      if (b == SYNC1) sync = 2;
      else if (b == SYNC0) g_st.skipped++;      // A5 A5: 後ろの A5 を先頭とみなして、探索を続ける
      else { sync = 0; g_st.skipped += 2; }
    }
  }
  sync = 0;

  uint8_t hdr[7];                                // type(1) + seq(4) + len(2)
  if (Serial.readBytes(hdr, 7) != 7) { g_st.timeouts++; return RX_BAD; }
  const uint8_t  type = hdr[0];
  const uint32_t seq = rd32(hdr + 1);
  const uint16_t len = rd16(hdr + 5);
  if (len > MAX_PAYLOAD || (type == TYPE_FRAME_XY && (len < 4 || (len & 1)))) {
    g_st.badLen++;                               // 偽の同期バイトだった可能性が高い
    return RX_BAD;
  }

  const int slot = pickFreeSlot();
  if (Serial.readBytes(g_buf[slot], len) != len) { g_st.timeouts++; return RX_BAD; }
  uint8_t cb[2];
  if (Serial.readBytes(cb, 2) != 2) { g_st.timeouts++; return RX_BAD; }

  uint16_t crc = crcUpdate(0xFFFF, hdr, 7);
  crc = crcUpdate(crc, g_buf[slot], len);
  if (crc != rd16(cb)) { g_st.crc++; return RX_BAD; }
  if (type != TYPE_FRAME_XY) return RX_BAD;      // 将来の形式（XYZ など）は、今は読み捨てる

  static bool haveSeq = false;
  static uint32_t lastSeq = 0;
  if (haveSeq && seq > lastSeq + 1) g_st.lost += seq - lastSeq - 1;   // 通し番号の飛び = 欠落
  haveSeq = true;
  lastSeq = seq;

  g_count[slot] = len / 2;
  portENTER_CRITICAL(&g_mux);
  g_front = slot;
  g_hasFrame = true;
  g_lastRxMs = millis();
  portEXIT_CRITICAL(&g_mux);
  g_st.ok++;
  return RX_OK;
}

static void printStats() {
  static uint32_t lastOk = 0, lastPasses = 0;
  const uint32_t passes = g_passes;
  Serial.printf("STAT ok=%lu (+%lu/s) crc=%lu len=%lu tmo=%lu lost=%lu skip=%lu passes/s=%lu\n",
                (unsigned long)g_st.ok, (unsigned long)(g_st.ok - lastOk), (unsigned long)g_st.crc,
                (unsigned long)g_st.badLen, (unsigned long)g_st.timeouts, (unsigned long)g_st.lost,
                (unsigned long)g_st.skipped, (unsigned long)(passes - lastPasses));
  lastOk = g_st.ok;
  lastPasses = passes;
}

static void rxTask(void*) {
  uint32_t lastPrint = millis();
  for (;;) {
    if (receivePacket() == RX_NONE) vTaskDelay(1);     // データが無ければ 1ms 休む（受信バッファが溜めてくれる）
    const uint32_t now = millis();
    if (now - lastPrint >= 1000) { printStats(); lastPrint = now; }
  }
}

// ---- 待機パターン（動く円）----
constexpr uint8_t IDLE_PTS = 120;
static uint8_t g_idleX[IDLE_PTS], g_idleY[IDLE_PTS];

static void drawIdle() {
  for (uint8_t i = 0; i < IDLE_PTS; i++) {
    dacWrite(PIN_X, g_idleX[i]);
    dacWrite(PIN_Y, g_idleY[i]);
  }
}

void setup() {
  for (uint8_t i = 0; i < IDLE_PTS; i++) {
    const float a = 2.0f * (float)M_PI * i / IDLE_PTS;
    g_idleX[i] = (uint8_t)lroundf(128.0f + 60.0f * cosf(a));
    g_idleY[i] = (uint8_t)lroundf(128.0f + 60.0f * sinf(a));
  }
  Serial.setRxBufferSize(RX_BUFFER_BYTES);   // begin() より前に呼ぶこと
  Serial.begin(BAUD);
  Serial.setTimeout(50);
  Serial.printf("osa_stream ready: baud=%lu\n", (unsigned long)BAUD);
  xTaskCreatePinnedToCore(rxTask, "rx", 8192, nullptr, 2, nullptr, 0);   // 受信はコア 0
}

void loop() {
  uint8_t idx = 0;
  uint16_t n = 0;
  bool have = false;
  portENTER_CRITICAL(&g_mux);
  if (g_hasFrame && (millis() - g_lastRxMs) < IDLE_TIMEOUT_MS) {
    idx = g_front;
    g_busy = idx;                            // この面は、描き終わるまで、受信側に上書きさせない
    n = g_count[idx];
    have = true;
  } else {
    g_busy = 0xFF;
  }
  portEXIT_CRITICAL(&g_mux);

  if (have) {
    const uint8_t* xy = g_buf[idx];
    for (uint16_t i = 0; i < n; i++) {
      dacWrite(PIN_X, xy[2 * i]);
      dacWrite(PIN_Y, xy[2 * i + 1]);
      if (POINT_DELAY_US) delayMicroseconds(POINT_DELAY_US);
    }
  } else {
    drawIdle();
  }
  g_passes++;
}
