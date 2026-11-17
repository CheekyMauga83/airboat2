#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>

// CONTROLLER ONLY. No ESP-NOW transmission; no joystick commands.
// Screen: SCK=12, SDA/MOSI=11, A0/DC=9, RESET=8, CS=10.
// VCC and backlight LED=3V3, GND=GND. Joystick GPIO4/5/6 untouched.
Adafruit_ST7735 screen(&SPI, 10, 9, 8);
uint32_t lastUpdate = 0;
uint32_t seconds = 0;

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  SPI.begin(12, -1, 11, 10);
  screen.initR(INITR_BLACKTAB);
  screen.setSPISpeed(4000000);
  screen.setRotation(1);
  screen.fillScreen(ST77XX_BLACK);
  screen.drawRect(0, 0, screen.width(), screen.height(), ST77XX_WHITE);
  screen.setTextWrap(false);
  screen.setTextColor(ST77XX_WHITE);
  screen.setTextSize(2);
  screen.setCursor(8, 8);
  screen.print("AIRBOAT");
  screen.setTextSize(1);
  screen.setCursor(8, 32);
  screen.print("ST7735 SCREEN TEST");
  screen.fillRect(8, 50, 45, 30, ST77XX_RED);
  screen.fillRect(57, 50, 45, 30, ST77XX_GREEN);
  screen.fillRect(106, 50, 45, 30, ST77XX_BLUE);
  screen.setCursor(8, 87);
  screen.print("RED    GREEN   BLUE");
  screen.setCursor(8, 114);
  screen.print("No motor commands");
}

void loop() {
  if (millis() - lastUpdate >= 1000) {
    lastUpdate = millis();
    screen.fillRect(8, 99, 140, 10, ST77XX_BLACK);
    screen.setCursor(8, 99);
    screen.print("Running: ");
    screen.print(++seconds);
    screen.print(" s");
    Serial.printf("SCREEN_TEST seconds=%lu (display response not sensed)\n", (unsigned long)seconds);
  }
  delay(1);
}
