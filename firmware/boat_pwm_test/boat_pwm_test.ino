#include <Arduino.h>

// Bench diagnostic. Disconnect both motors for every test.
// Commands 1–4 select left IN1, left IN2, right IN1, right IN2. 0 stops the test.
// L/R hold a driver's IN1 HIGH so a meter can read its unloaded motor output.
constexpr uint8_t kPins[] = {15, 16, 17, 14};
constexpr uint32_t kFrequencyHz = 20000;
constexpr uint8_t kResolutionBits = 8;
constexpr uint32_t kTestDuty = 64;  // 25% of 256 PWM counts.
constexpr uint32_t kTestDurationMs = 10000;

int activePin = -1;
bool pwmActive = false;
uint32_t startedAt = 0;

void stopTest() {
  if (activePin < 0) return;
  if (pwmActive) {
    ledcWrite(activePin, 0);
    ledcDetach(activePin);
    pinMode(activePin, OUTPUT);
  }
  digitalWrite(activePin, LOW);
  Serial.printf("STOP GPIO%d LOW\n", activePin);
  activePin = -1;
  pwmActive = false;
}

void setup() {
  for (uint8_t pin : kPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
}

void loop() {
  if (activePin >= 0 && millis() - startedAt >= kTestDurationMs) {
    stopTest();
  }

  const int command = Serial.read();
  if (command == '0') {
    stopTest();
  } else if ((command == 'L' || command == 'R') && activePin < 0) {
    activePin = command == 'L' ? kPins[0] : kPins[2];
    startedAt = millis();
    digitalWrite(activePin, HIGH);
    Serial.printf("START unloaded output GPIO%d HIGH for 10 seconds\n", activePin);
  } else if (command >= '1' && command <= '4' && activePin < 0) {
    const uint8_t pin = kPins[command - '1'];
    if (!ledcAttach(pin, kFrequencyHz, kResolutionBits)) {
      Serial.println("ERROR PWM attach failed");
    } else {
      activePin = pin;
      pwmActive = true;
      startedAt = millis();
      if (!ledcWrite(pin, kTestDuty)) {
        stopTest();
        Serial.println("ERROR PWM write failed");
      } else {
        // LEDC latches the duty on a PWM cycle boundary.
        delayMicroseconds(100);
        const uint32_t frequency = ledcReadFreq(pin);
        const uint32_t duty = ledcRead(pin);
        if (frequency == 0 || duty != kTestDuty) {
          stopTest();
          Serial.println("ERROR unexpected PWM readback");
        } else {
          Serial.printf("START GPIO%u %lu Hz duty=%lu/256 for 10 seconds\n", pin,
                        static_cast<unsigned long>(frequency), static_cast<unsigned long>(duty));
        }
      }
    }
  }

  static uint32_t lastStatus = 0;
  if (activePin < 0 && millis() - lastStatus >= 1000) {
    lastStatus = millis();
    Serial.println("READY | all outputs LOW | 1=GPIO15 2=GPIO16 3=GPIO17 4=GPIO14 | L/R=unloaded output");
  }
  delay(2);
}
