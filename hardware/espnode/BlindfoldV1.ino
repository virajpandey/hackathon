// Blindfold stage: XIAO ESP32C6 story screen + cheat button.
//
// The laptop bridge (c6_bridge.py) sends one command per line over USB serial:
//   W <token>   add a token to the story. A leading space means a new word;
//               no leading space continues the current word (llama2.c sub-words).
//   L           line break
//   N           new story: clear the screen
//   X           the chip caught a cheat: flash CHEAT CAUGHT, then back to the story
//   ?           identify -> replies "HELLO BLINDFOLD-C6"
// The C6 sends back:
//   CHEAT              cheat button pressed
//   REUSE 1 / REUSE 0  reuse switch flipped (optional switch)
//
// Wiring (XIAO ESP32C6 or XIAO ESP32C3; same D-pin labels on both):
//   LCD I2C backpack: SDA -> D4, SCL -> D5, GND -> GND, VCC -> see README
//   Cheat button:     D1 -> button -> GND   (the on-board BOOT button also works)
//   Reuse switch:     D2 -> switch -> GND   (optional; the dashboard has the same toggle)
//
// Board: Tools > Board > XIAO_ESP32C6 (or XIAO_ESP32C3), Tools > USB CDC On Boot > Enabled.

#include <Wire.h>

#if !ARDUINO_USB_CDC_ON_BOOT
#error "Set Tools > USB CDC On Boot > Enabled so Serial talks over the USB-C cable"
#endif

const int PIN_CHEAT = D1;
const int PIN_BOOT = 9;    // on-board BOOT button
const int PIN_REUSE = D2;
const int LED_ON = LOW;    // XIAO ESP32C6 user LED (GPIO15) is active-low; the XIAO ESP32C3 has none

void led(bool on) {
#ifdef LED_BUILTIN
  digitalWrite(LED_BUILTIN, on ? LED_ON : !LED_ON);
#endif
}

// ---------- 16x2 LCD through a PCF8574 backpack ----------
#define BL 0x08
#define EN 0x04
#define RS 0x01

uint8_t lcdAddr = 0;
uint8_t backlight = BL;

void expanderWrite(uint8_t v) {
  if (!lcdAddr) return;
  Wire.beginTransmission(lcdAddr);
  Wire.write(v | backlight);
  Wire.endTransmission();
}

void write4(uint8_t nib, bool rs) {
  uint8_t d = (nib & 0xF0) | (rs ? RS : 0);
  expanderWrite(d | EN);
  delayMicroseconds(1);
  expanderWrite(d);
  delayMicroseconds(50);
}

void send(uint8_t b, bool rs) {
  write4(b & 0xF0, rs);
  write4(b << 4, rs);
}

void cmd(uint8_t c) {
  send(c, false);
  if (c == 0x01 || c == 0x02) delay(2);
}

void lcdInit() {
  delay(50);
  for (int i = 0; i < 3; i++) { write4(0x30, false); delay(5); }
  write4(0x20, false);  // 4-bit mode
  cmd(0x28);            // 2 lines, 5x8 font
  cmd(0x0C);            // display on, cursor off
  cmd(0x06);            // cursor moves right
  cmd(0x01);            // clear
}

void lcdRow(uint8_t row, const char *s) {  // write exactly 16 chars, padded with spaces
  cmd(0x80 | (row ? 0x40 : 0));
  for (int i = 0; i < 16; i++) send(*s ? *s++ : ' ', true);
}

bool i2cFound(uint8_t a) {
  Wire.beginTransmission(a);
  return Wire.endTransmission() == 0;
}

// ---------- story as a two-line teleprompter ----------
char line0[17] = "", line1[17] = "";
int len1 = 0;
int wordStart = 0;  // where the current word begins on line 1
bool dirty0 = false, dirty1 = false;

void clearStory() {
  line0[0] = line1[0] = 0;
  len1 = wordStart = 0;
  dirty0 = dirty1 = true;
}

void scrollUp() {
  strcpy(line0, line1);
  line1[0] = 0;
  len1 = wordStart = 0;
  dirty0 = dirty1 = true;
}

void append(const char *t, int n) {
  n = min(n, 16 - len1);
  memcpy(line1 + len1, t, n);
  len1 += n;
  line1[len1] = 0;
  dirty1 = true;
}

void addToken(const char *t) {
  bool newWord = (*t == ' ');
  while (*t == ' ') t++;
  int n = min((int)strlen(t), 16);
  if (n == 0) return;

  if (len1 == 0) {
    wordStart = 0;
    append(t, n);
  } else if (newWord) {
    if (len1 + 1 + n <= 16) {
      append(" ", 1);
      wordStart = len1;
    } else {
      scrollUp();
    }
    append(t, n);
  } else if (len1 + n <= 16) {  // sub-word that fits
    append(t, n);
  } else if (wordStart > 0) {   // carry the half-built word down to the next line
    char part[17];
    int pl = len1 - wordStart;
    memcpy(part, line1 + wordStart, pl);
    len1 = wordStart - 1;  // also drop the space before it
    line1[len1] = 0;
    scrollUp();
    append(part, pl);
    append(t, n);
  } else {                      // a word longer than the screen: hard wrap
    scrollUp();
    append(t, n);
  }
}

// ---------- CHEAT CAUGHT flash ----------
uint32_t cheatUntil = 0, nextBlink = 0;

void startCheatFlash() {
  cheatUntil = millis() + 3000;
  nextBlink = 0;
  lcdRow(0, " CHEAT CAUGHT!");
  lcdRow(1, "answer rejected");
}

void serviceCheatFlash() {
  if (!cheatUntil) return;
  uint32_t now = millis();
  if ((int32_t)(now - cheatUntil) >= 0) {
    cheatUntil = 0;
    backlight = BL;
    expanderWrite(0);
    dirty0 = dirty1 = true;  // put the story back
    return;
  }
  if (now >= nextBlink && now < cheatUntil - 1500) {  // blink for the first 1.5 s
    backlight ^= BL;
    expanderWrite(0);
    nextBlink = now + 180;
  } else if (now >= cheatUntil - 1500 && backlight != BL) {
    backlight = BL;
    expanderWrite(0);
  }
}

// ---------- buttons ----------
struct Input {  // member functions, so Arduino's prototype generator leaves them alone
  int pin;
  bool stable, last;
  uint32_t since;

  void begin() {
    pinMode(pin, INPUT_PULLUP);
    stable = last = digitalRead(pin);
    since = millis();
  }

  bool changed() {  // debounced edge in either direction
    bool r = digitalRead(pin);
    if (r != last) { last = r; since = millis(); }
    if (millis() - since > 25 && r != stable) { stable = r; return true; }
    return false;
  }
};
Input cheatBtn{PIN_CHEAT}, bootBtn{PIN_BOOT}, reuseSw{PIN_REUSE};

uint32_t ledOffAt = 0;

void pollInputs() {
  bool cheat = false;
  if (cheatBtn.changed() && cheatBtn.stable == LOW) cheat = true;
  if (bootBtn.changed() && bootBtn.stable == LOW) cheat = true;
  if (cheat) {
    Serial.println("CHEAT");
    led(true);
    ledOffAt = millis() + 300;
  }
  if (reuseSw.changed()) Serial.println(reuseSw.stable == LOW ? "REUSE 1" : "REUSE 0");
  if (ledOffAt && (int32_t)(millis() - ledOffAt) >= 0) {
    led(false);
    ledOffAt = 0;
  }
}

// ---------- serial commands ----------
char rx[96];
int rxLen = 0;

void hello() {
  if (lcdAddr) {
    Serial.printf("HELLO BLINDFOLD-C6 lcd=0x%02X\n", lcdAddr);
    return;
  }
  String found;  // scan first, then print one whole line
  for (uint8_t a = 0x08; a < 0x78; a++)
    if (i2cFound(a)) found += String(" 0x") + String(a, HEX);
  Serial.println("HELLO BLINDFOLD-C6 lcd=none i2c=[" + found + " ] (check SDA->D4, SCL->D5, VCC, GND)");
}

uint8_t findLcd() {  // PCF8574 backpacks live at 0x20-0x27, PCF8574A at 0x38-0x3F
  if (i2cFound(0x27)) return 0x27;
  if (i2cFound(0x3F)) return 0x3F;
  for (uint8_t a = 0x20; a <= 0x27; a++) if (i2cFound(a)) return a;
  for (uint8_t a = 0x38; a <= 0x3F; a++) if (i2cFound(a)) return a;
  return 0;
}

void handleLine(char *s) {
  switch (s[0]) {
    case 'W': if (s[1] == ' ') addToken(s + 2); break;
    case 'L': scrollUp(); break;
    case 'N': clearStory(); break;
    case 'X': startCheatFlash(); break;
    case '?':  // the bridge asks on connect; also picks up an LCD wired after boot
      if (!lcdAddr && (lcdAddr = findLcd())) {
        lcdInit();
        dirty0 = dirty1 = true;
      }
      hello();
      break;
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      rx[rxLen] = 0;
      handleLine(rx);
      rxLen = 0;
    } else if (c != '\r' && rxLen < (int)sizeof(rx) - 1) {
      rx[rxLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // never stall if the laptop is not reading
#ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
#endif
  led(false);
  cheatBtn.begin();
  bootBtn.begin();
  reuseSw.begin();

  Wire.begin(D4, D5);
  Wire.setTimeOut(10);  // a stuck or miswired bus fails fast instead of 50 ms per address
  lcdAddr = findLcd();
  if (lcdAddr) {
    lcdInit();
    lcdRow(0, "   BLINDFOLD");
    lcdRow(1, "waiting for chip");
  }
  delay(300);
  hello();
}

uint32_t nextLcdTry = 0;

void loop() {
  readSerial();
  pollInputs();
  serviceCheatFlash();
  if (!lcdAddr && (int32_t)(millis() - nextLcdTry) >= 0) {  // LCD wired after boot: pick it up
    nextLcdTry = millis() + 2000;
    if ((lcdAddr = findLcd())) {
      lcdInit();
      dirty0 = dirty1 = true;
      hello();
    }
  }
  if (!cheatUntil) {
    if (dirty0) { lcdRow(0, line0); dirty0 = false; }
    if (dirty1) { lcdRow(1, line1); dirty1 = false; }
  }
}