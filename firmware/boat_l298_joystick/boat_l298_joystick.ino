#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <cstring>

// Bench driving with both propellers removed. Click the centered stick button
// to arm. Press it again to disarm.
constexpr uint8_t kLeftIn1 = 17; // L298 IN3 -> left OUT3/OUT4
constexpr uint8_t kLeftIn2 = 14; // L298 IN4
constexpr uint8_t kRightIn1 = 15; // L298 IN1 -> right OUT1/OUT2
constexpr uint8_t kRightIn2 = 16; // L298 IN2
constexpr uint8_t kMotorPins[] = {kLeftIn2, kRightIn2, kLeftIn1, kRightIn1};
constexpr uint8_t kControllerMac[] = {0xe0, 0x72, 0xa1, 0xd5, 0x25, 0x90};
constexpr uint8_t kChannel = 1;
constexpr uint32_t kPacketMagic = 0x41495242;
constexpr uint32_t kLinkTimeoutMs = 150;
constexpr uint32_t kMaxRunMs = 3000;
constexpr uint32_t kPwmFrequency = 1000; // Matches L298 bench tests.
constexpr uint8_t kPwmBits = 8;
constexpr uint32_t kPwmPeriodTicks = 1U << kPwmBits;
constexpr uint8_t kMaxDuty = 128;  // 50% drive duty. ENA/ENB jumpers installed.
constexpr int kCenterX = 1750;
constexpr int kCenterY = 1750;
constexpr int kDeadzone = 250; // Inclusive neutral range: 1500..2000.
constexpr int kAxisMaximum = 3000; // Saturate high-side demand at this reading.
constexpr uint8_t kTurbidityPin = 4;

void sampleTurbidity() {
  static uint32_t lastSample = 0, rawSum = 0, mvSum = 0;
  static uint8_t count = 0;
  static bool clipped = false;
  if (millis() - lastSample < 25) return;
  lastSample = millis();
  const uint32_t raw = analogRead(kTurbidityPin);
  const uint32_t mv = analogReadMilliVolts(kTurbidityPin);
  rawSum += raw;
  mvSum += mv;
  clipped |= raw >= 4090 || mv >= 3100;
  if (++count < 20) return;
  // Separate consecutive raw/calibrated conversions, averaged over 500 ms.
  // Existing divider: sensor --10k-- GPIO4 --20k-- GND. Undo with factor 1.5.
  Serial.printf("TURBIDITY | raw=%lu | adc_mV=%.1f | sensor_V_est=%.3f | status=%s | NTU=uncalibrated\n",
    (unsigned long)(rawSum / count), float(mvSum) / count,
    float(mvSum) / count * 0.0015f,
    clipped ? "ADC_RANGE_LIMIT" : rawSum / count < 10 ? "LOW_SIGNAL_CHECK_POWER_WIRING" : "READING");
  count = 0; rawSum = 0; mvSum = 0; clipped = false;
}

// Same little-endian packet as controller_link_test and boat_link_test.
struct ControlPacket {
  uint32_t magic;
  uint32_t sequence;
  uint16_t x;
  uint16_t y;
  uint8_t button;
  uint8_t version;
  uint16_t reserved;
};
static_assert(sizeof(ControlPacket) == 16, "Unexpected packet layout");

struct ReceivedCommand {
  ControlPacket packet;
  uint32_t receivedAt;
};

QueueHandle_t commandQueue = nullptr;
bool armed = false;
bool running = false;
bool runLimitReached = false;
uint32_t runStartedAt = 0;
uint8_t appliedLeft = 0;
uint8_t appliedRight = 0;

void forceLow() {
  for (uint8_t pin : kMotorPins) {
    if (pin == kLeftIn1 || pin == kRightIn1) ledcDetach(pin);
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
}

void haltWithError(const char *message) {
  forceLow();
  while (true) {
    Serial.println(message);
    delay(500);
  }
}

void setDrive(uint8_t left, uint8_t right) {
  if (left == appliedLeft && right == appliedRight) return;
  // Each second input stays LOW. PWM first input gives drive/brake with ENA/ENB HIGH.
  if (!ledcWrite(kLeftIn1, left) || !ledcWrite(kRightIn1, right)) {
    haltWithError("ERROR PWM write failed; outputs forced LOW");
  }
  appliedLeft = left;
  appliedRight = right;
}

void disarm(const char *reason) {
  setDrive(0, 0);
  armed = false;
  running = false;
  runLimitReached = false;
  Serial.println(reason);
}

void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (!info || !data || length != sizeof(ControlPacket) ||
      memcmp(info->src_addr, kControllerMac, sizeof(kControllerMac)) != 0) return;

  ReceivedCommand command{};
  memcpy(&command.packet, data, sizeof(command.packet));
  const auto &packet = command.packet;
  if (packet.magic != kPacketMagic || packet.version != 1 || packet.reserved != 0 ||
      packet.x > 4095 || packet.y > 4095 || packet.button > 1) return;

  command.receivedAt = millis();
  xQueueOverwrite(commandQueue, &command);
}

float axisDemand(int raw, int center) {
  const int offset = raw - center;
  if (abs(offset) <= kDeadzone) return 0.0f;
  if (offset > 0) return min(1.0f, float(offset - kDeadzone) / (kAxisMaximum - center - kDeadzone));
  return float(offset + kDeadzone) / (center - kDeadzone);
}

void setup() {
  for (uint8_t pin : kMotorPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  pinMode(kTurbidityPin, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(kTurbidityPin, ADC_11db);
  if (!ledcAttach(kLeftIn1, kPwmFrequency, kPwmBits) || !ledcWrite(kLeftIn1, 0) ||
      !ledcAttach(kRightIn1, kPwmFrequency, kPwmBits) || !ledcWrite(kRightIn1, 0)) {
    haltWithError("ERROR PWM unavailable");
  }
  commandQueue = xQueueCreate(1, sizeof(ReceivedCommand));
  if (!commandQueue) haltWithError("ERROR receive queue unavailable");
  if (!WiFi.mode(WIFI_STA) || esp_wifi_set_channel(kChannel, WIFI_SECOND_CHAN_NONE) != ESP_OK ||
      esp_now_init() != ESP_OK || esp_now_register_recv_cb(onReceive) != ESP_OK) {
    haltWithError("ERROR radio setup failed");
  }
}

void loop() {
  static ReceivedCommand latest{};
  static bool received = false;
  static bool buttonWasPressed = true;
  static bool armPressPending = false;
  static uint32_t lastStatus = 0;
  ReceivedCommand incoming{};
  if (xQueueReceive(commandQueue, &incoming, 0) == pdTRUE) {
    latest = incoming;
    received = true;
  }
  const uint32_t now = millis();
  const int usbCommand = Serial.read();
  const bool fresh = received && now - latest.receivedAt < kLinkTimeoutMs;
  const bool pressed = latest.packet.button != 0;
  const float turn = axisDemand(latest.packet.x, kCenterX);
  const float forward = -axisDemand(latest.packet.y, kCenterY);
  const bool centered = turn == 0.0f && forward == 0.0f;

  if (!fresh || usbCommand == '0') {
    if (armed) disarm(fresh ? "STOP | USB stop" : "STOP | controller link lost");
    armPressPending = false;
    buttonWasPressed = true;
  } else {
    if (pressed && !buttonWasPressed) {
      if (armed) disarm("STOP | stick button");
      else armPressPending = centered;
    }
    if (!centered) armPressPending = false;
    if (!pressed && buttonWasPressed && armPressPending) {
      armPressPending = false;
      armed = true;
      Serial.println("ARMED | props-off drive test");
    }
    buttonWasPressed = pressed;

    if (centered) runLimitReached = false;
    if (armed && !pressed && !runLimitReached) {
      const float left = forward < 0 ? 0.0f : constrain(forward + turn, 0.0f, 1.0f);
      const float right = forward < 0 ? 0.0f : constrain(forward - turn, 0.0f, 1.0f);
      const uint8_t leftDuty = lroundf(left * kMaxDuty);
      const uint8_t rightDuty = lroundf(right * kMaxDuty);
      if (leftDuty == 0 && rightDuty == 0) {
        setDrive(0, 0);
        running = false;
      } else {
        if (!running) runStartedAt = now;
        running = true;
        if (now - runStartedAt >= kMaxRunMs) {
          setDrive(0, 0);
          running = false;
          runLimitReached = true;
          Serial.println("STOP | bench run limit reached; center stick to resume");
        } else {
          setDrive(leftDuty, rightDuty);
        }
      }
    }
  }

  if (now - lastStatus >= 250) {
    lastStatus = now;
    Serial.printf("L298 DRIVE | %s | %s | left=%u right=%u\n",
                  armed ? "ARMED" : "DISARMED",
                  !fresh ? "waiting for controller" : centered ? "centered" : "stick off-center",
                  static_cast<unsigned>(appliedLeft), static_cast<unsigned>(appliedRight));
    if (appliedLeft || appliedRight) {
      Serial.printf("PWM | X=%u Y=%u | IN1 drive ticks left=%lu right=%lu of %lu | Hz=%lu\n",
                    static_cast<unsigned>(latest.packet.x),
                    static_cast<unsigned>(latest.packet.y),
                    static_cast<unsigned long>(ledcRead(kLeftIn1)),
                    static_cast<unsigned long>(ledcRead(kRightIn1)),
                    static_cast<unsigned long>(kPwmPeriodTicks),
                    static_cast<unsigned long>(ledcReadFreq(appliedLeft ? kLeftIn1 : kRightIn1)));
    }
  }
  sampleTurbidity();
  delay(1);
}
