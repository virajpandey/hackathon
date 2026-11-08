// Blindfold node on an ESP32 (XIAO S3, C3 or C6): computes its share of the note model over USB.
// It holds only the public model and receives only random-looking shares; it never sees the note.
// Same wire format as node.py: 0xB1, type byte, uint32 count, count x uint64 (little-endian), mod P = 2^61-1.
//
// No-button flashing: keep USBMode=hwcdc. USB I/O uses ESP-IDF's usb_serial_jtag driver (see s3link.ino).
// The text line BOOT jumps to flash mode on the S3 (leave it with esptool --after watchdog-reset).
// Optional screen: a 16x2 character LCD on an I2C backpack at 0x27 (SDA D4, SCL D5). If present, it shows only
// what this node receives: random-looking numbers. Small driver written here, no extra library.
#include <Wire.h>
#include "driver/usb_serial_jtag.h"
#if CONFIG_IDF_TARGET_ESP32S3
#include "soc/rtc_cntl_reg.h"
#endif
#include "model.h"

static const uint64_t P = (1ULL << 61) - 1;
static uint64_t in[3 * N_IN + 4 * HID], out[2 * HID];
static uint64_t a[HID], at[HID], a2[HID], a2t[HID];
static uint64_t idx, alpha, lieAt = P - 1, chr;

static inline uint64_t red(uint64_t x) { x = (x & P) + (x >> 61); return x >= P ? x - P : x; }
static inline uint64_t addm(uint64_t x, uint64_t y) { return red(x + y); }
static inline uint64_t subm(uint64_t x, uint64_t y) { return x >= y ? x - y : x + P - y; }
static inline uint64_t wm(int64_t w) { return w >= 0 ? (uint64_t)w : P - (uint64_t)(-w); }
static uint64_t mulm(uint64_t x, uint64_t y) {  // x, y < P; 2^61 = 1 and 2^64 = 8 (mod P)
  uint64_t x0 = (uint32_t)x, x1 = x >> 32, y0 = (uint32_t)y, y1 = y >> 32;
  uint64_t mid = x1 * y0 + x0 * y1;
  uint64_t r = ((x1 * y1) << 3) + (mid >> 29) + ((mid & ((1ULL << 29) - 1)) << 32);
  return red(red(r) + red(x0 * y0));
}

static const uint8_t LCD = 0x27, BL = 0x08, EN = 0x04, RS = 0x01;
static bool lcdOn = false;
static void lcdNib(uint8_t n) {
  Wire.beginTransmission(LCD);
  Wire.write((n & 0xF0) | BL | EN);
  Wire.write((n & 0xF0) | BL);
  Wire.endTransmission();
}
static void lcdByte(uint8_t v, uint8_t rs) {
  uint8_t hi = (v & 0xF0) | rs | BL, lo = (uint8_t)(v << 4) | rs | BL;
  Wire.beginTransmission(LCD);
  Wire.write(hi | EN); Wire.write(hi); Wire.write(lo | EN); Wire.write(lo);
  if (Wire.endTransmission() != 0) lcdOn = false;  // screen fell off: stop writing, the loop keeps looking
}
static void lcdLine(int row, const char *s) {
  if (!lcdOn) return;
  lcdByte(0x80 | (row ? 0x40 : 0), 0);
  for (int i = 0; i < 16 && lcdOn; i++) lcdByte(*s ? *s++ : ' ', RS);
}
static void lcdInit() {
  Wire.begin();
  Wire.setClock(100000);
  Wire.setTimeOut(10);  // a stuck bus must never stall the node
  Wire.beginTransmission(LCD);
  if (Wire.endTransmission() != 0) return;
  lcdOn = true;
  delay(50);
  lcdNib(0x30); delay(5); lcdNib(0x30); delay(1); lcdNib(0x30); delay(1); lcdNib(0x20); delay(1);
  lcdByte(0x28, 0); lcdByte(0x0C, 0); lcdByte(0x06, 0); lcdByte(0x01, 0); delay(3);
  lcdLine(0, "BLINDFOLD node");
  lcdLine(1, "waiting for Mac");
}

static bool rd(void *dst, size_t n) {
  uint8_t *p = (uint8_t *)dst;
  while (n) {
    int r = usb_serial_jtag_read_bytes(p, n, pdMS_TO_TICKS(3000));
    if (r <= 0) return false;
    p += r;
    n -= r;
  }
  return true;
}

static void wr(const void *src, size_t n) {
  const uint8_t *p = (const uint8_t *)src;
  while (n) {
    int w = usb_serial_jtag_write_bytes(p, n < 4096 ? n : 4096, pdMS_TO_TICKS(2000));
    if (w <= 0) return;
    p += w;
    n -= w;
  }
}

static void send(char kind, const uint64_t *v, uint32_t n) {
  uint8_t hdr[6] = {0xB1, (uint8_t)kind};
  memcpy(hdr + 2, &n, 4);
  wr(hdr, 6);
  wr(v, 8 * n);
}

static void stepIn() {
  const uint64_t *eps = in, *r = in + N_IN, *rt = in + 2 * N_IN, *pa = in + 3 * N_IN;
  memcpy(a, pa, sizeof a);
  memcpy(at, pa + HID, sizeof at);
  memcpy(a2, pa + 2 * HID, sizeof a2);
  memcpy(a2t, pa + 3 * HID, sizeof a2t);
  static uint64_t x[N_IN], xt[N_IN];
  for (int j = 0; j < N_IN; j++) {
    x[j] = idx == 0 ? addm(r[j], eps[j]) : r[j];
    xt[j] = addm(rt[j], mulm(alpha, eps[j]));
  }
  for (int k = 0; k < HID; k++) {
    uint64_t z = idx == 0 ? wm(MB1[k]) : 0, zt = mulm(alpha, wm(MB1[k]));
    for (int j = 0; j < N_IN; j++) {
      uint64_t w = wm(MW1[j][k]);
      z = addm(z, mulm(w, x[j]));
      zt = addm(zt, mulm(w, xt[j]));
    }
    out[k] = subm(z, a[k]);
    out[HID + k] = subm(zt, at[k]);
  }
  send('D', out, 2 * HID);
  char l0[17], l1[17];
  snprintf(l0, sizeof l0, "node %c sees: %s", 'A' + (int)idx, chr == lieAt ? "LIE" : "");
  snprintf(l1, sizeof l1, "%08lx%08lx", (unsigned long)(x[0] >> 32), (unsigned long)(uint32_t)x[0]);
  lcdLine(0, l0);
  lcdLine(1, l1);
}

static void stepOut() {
  static uint64_t y[HID], yt[HID];
  for (int k = 0; k < HID; k++) {
    uint64_t d = in[k], dd = mulm(d, d);
    y[k] = addm(addm(a2[k], mulm(2 * d % P, a[k])), idx == 0 ? dd : 0);
    yt[k] = addm(addm(a2t[k], mulm(2 * d % P, at[k])), mulm(alpha, dd));
  }
  if (chr == lieAt) y[0] = addm(y[0], 1);  // the demo's lie button
  for (int v = 0; v < VOC; v++) {
    uint64_t l = idx == 0 ? wm(MB2[v]) : 0, lt = mulm(alpha, wm(MB2[v]));
    for (int k = 0; k < HID; k++) {
      uint64_t w = wm(MW2[k][v]);
      l = addm(l, mulm(w, y[k]));
      lt = addm(lt, mulm(w, yt[k]));
    }
    out[v] = l;
    out[VOC + v] = lt;
  }
  chr++;
  send('L', out, 2 * VOC);
}

void setup() {
  usb_serial_jtag_driver_config_t cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
  cfg.rx_buffer_size = 16384;
  cfg.tx_buffer_size = 8192;
  usb_serial_jtag_driver_install(&cfg);
  const char *hello = "BLINDFOLD node ready\r\n";
  usb_serial_jtag_write_bytes(hello, strlen(hello), pdMS_TO_TICKS(20));
  lcdInit();
}

void loop() {
  static char line[16];
  static int len = 0;
  static uint32_t lastTry = 0;
  if (!lcdOn && millis() - lastTry > 2000) {  // loose screen wires: keep looking, no replug needed
    lastTry = millis();
    lcdInit();
  }
  uint8_t c;
  if (usb_serial_jtag_read_bytes(&c, 1, pdMS_TO_TICKS(100)) != 1) return;
  if (c == 0xB1) {
    uint8_t kind;
    uint32_t n;
    if (!rd(&kind, 1) || !rd(&n, 4) || n > sizeof in / 8 || !rd(in, 8 * n)) return;
    if (kind == 'S') {
      idx = in[0];
      alpha = in[1];
      lieAt = in[2];
      chr = 0;
      send('K', &idx, 1);
      char l0[17];
      snprintf(l0, sizeof l0, "node %c: ready", 'A' + (int)idx);
      lcdLine(0, l0);
      lcdLine(1, "note: never sent");
    } else if (kind == 'X') {
      stepIn();
    } else if (kind == 'O') {
      stepOut();
    }
  } else if (c == '\n') {
    line[len] = 0;
    len = 0;
#if CONFIG_IDF_TARGET_ESP32S3
    if (!strcmp(line, "BOOT")) {
      usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(50));
      REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
      esp_restart();
    }
#endif
  } else if (c != '\r' && len < (int)sizeof line - 1) {
    line[len++] = c;
  }
}
