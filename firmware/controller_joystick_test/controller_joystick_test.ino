#include <Arduino.h>

// Controller ESP32-S3 only: joystick VCC -> 3V3, GND -> GND.
constexpr uint8_t kJoystickX = 4;
constexpr uint8_t kJoystickY = 5;
constexpr uint8_t kJoystickButton = 6;
constexpr uint8_t kSamples = 16;

uint16_t readAxis(uint8_t pin) {
  uint32_t sum = 0;
  for (uint8_t i = 0; i < kSamples; ++i) {
    sum += analogRead(pin);
  }
  return static_cast<uint16_t>((sum + kSamples / 2) / kSamples);
}

void setup() {
  Serial.begin(115200);
  const uint32_t started = millis();
  while (!Serial && millis() - started < 3000) {
    delay(10);
  }

  pinMode(kJoystickX, INPUT);
  pinMode(kJoystickY, INPUT);
  pinMode(kJoystickButton, INPUT_PULLUP);
  analogReadResolution(12);
  analogSetPinAttenuation(kJoystickX, ADC_11db);
  analogSetPinAttenuation(kJoystickY, ADC_11db);

  Serial.println("Airboat controller joystick test");
  Serial.println("X=GPIO4 Y=GPIO5 button=GPIO6; raw ADC range 0..4095");
  Serial.println("Record center, left, right, forward, backward, and button press.");
}

void loop() {
  const uint16_t x = readAxis(kJoystickX);
  const uint16_t y = readAxis(kJoystickY);
  const bool pressed = digitalRead(kJoystickButton) == LOW;
  Serial.printf("X=%4u  Y=%4u  BUTTON=%s\n",
                static_cast<unsigned>(x), static_cast<unsigned>(y),
                pressed ? "PRESSED" : "released");
  delay(100);
}
