#include <Wire.h>

#define BL 0x08
#define EN 0x04
#define RS 0x01

uint8_t ADDR = 0;

void write4(uint8_t nib, bool rs) {
  uint8_t data = (nib & 0xF0) | BL | (rs ? RS : 0);
  Wire.beginTransmission(ADDR);
  Wire.write(data | EN);
  Wire.endTransmission();
  delayMicroseconds(1);
  Wire.beginTransmission(ADDR);
  Wire.write(data);
  Wire.endTransmission();
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

void lcdMove(uint8_t col, uint8_t row) {
  cmd(0x80 | (col + (row ? 0x40 : 0)));
}

void lcdPrint(const char *s) {
  while (*s) send(*s++, true);
}

bool found(uint8_t a) {
  Wire.beginTransmission(a);
  return Wire.endTransmission() == 0;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Wire.begin(6, 7);  // SDA = D4, SCL = D5

  if (found(0x27)) ADDR = 0x27;
  else if (found(0x3F)) ADDR = 0x3F;

  if (ADDR == 0) {
    Serial.println("No LCD found - check wiring");
    return;
  }

  Serial.print("LCD found at 0x");
  Serial.println(ADDR, HEX);

  lcdInit();
  lcdMove(0, 0);
  lcdPrint("Hello World!");
  Serial.println("Message sent to LCD");
}

void loop() {}