#include <Arduino.h>

// Bench test with both propellers removed. P pulses left, R pulses right.
// 0 stops the active pulse immediately.
constexpr uint8_t kLeftIn1 = 15;
constexpr uint8_t kRightIn1 = 13;
constexpr uint8_t kMotorPins[] = {kLeftIn1, 16, kRightIn1, 14};
constexpr uint32_t kFrequencyHz = 20000;
constexpr uint8_t kResolutionBits = 8;
constexpr uint32_t kDutyCounts = 51;  // About 20% of 256 counts.
constexpr uint32_t kPulseMs = 200;
constexpr uint32_t kCooldownMs = 1000;

bool pwmReady = false;
bool pulseActive = false;
uint8_t activePin = kLeftIn1;
uint32_t startedAt = 0;
uint32_t stoppedAt = 0;

void stopPulse() {
  if (!ledcWrite(activePin, 0)) {
    ledcDetach(activePin);
    pinMode(activePin, OUTPUT);
    digitalWrite(activePin, LOW);
    pwmReady = false;
  }
  pulseActive = false;
  stoppedAt = millis();
  Serial.printf("STOP %s motor | duty=0\n", activePin == kLeftIn1 ? "left" : "right");
}

void setup() {
  for (uint8_t pin : kMotorPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  pwmReady = ledcAttach(kLeftIn1, kFrequencyHz, kResolutionBits) && ledcWrite(kLeftIn1, 0) &&
             ledcAttach(kRightIn1, kFrequencyHz, kResolutionBits) && ledcWrite(kRightIn1, 0);
  stoppedAt = millis();
}

void loop() {
  const uint32_t now = millis();
  const int command = Serial.read();
  if (pulseActive && (command == '0' || now - startedAt >= kPulseMs || !Serial)) {
    stopPulse();
  } else if ((command == 'P' || command == 'R') && pwmReady && !pulseActive &&
             now - stoppedAt >= kCooldownMs) {
    activePin = command == 'P' ? kLeftIn1 : kRightIn1;
    startedAt = now;
    if (ledcWrite(activePin, kDutyCounts)) {
      pulseActive = true;
      Serial.printf("START %s motor | 200 ms | duty=51/256\n", activePin == kLeftIn1 ? "left" : "right");
    } else {
      stopPulse();
      pwmReady = false;
    }
  }

  static uint32_t lastStatus = 0;
  if (!pulseActive && now - lastStatus >= 1000) {
    lastStatus = now;
    Serial.println(pwmReady ? "READY | motor pulse test | duty=0" : "ERROR motor PWM unavailable");
  }
  delay(1);
}
