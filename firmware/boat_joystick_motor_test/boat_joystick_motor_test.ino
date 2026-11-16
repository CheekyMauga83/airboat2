#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <cstring>

// Props off. Send A over USB with the stick centered to allow one pulse.
// Send 0, release the stick, or press the stick button to stop.
constexpr uint8_t kLeftIn1 = 15;
constexpr uint8_t kRightIn1 = 13;
constexpr uint8_t kMotorPins[] = {kLeftIn1, 16, kRightIn1, 14};
constexpr uint8_t kControllerMac[] = {0xe0, 0x72, 0xa1, 0xd5, 0x25, 0x90};
constexpr uint8_t kChannel = 1;
constexpr uint32_t kPacketMagic = 0x41495242;
constexpr uint32_t kLinkTimeoutMs = 150;
constexpr uint32_t kArmTimeoutMs = 15000;
constexpr uint32_t kCenterHoldMs = 250;
constexpr uint32_t kPulseMs = 200;
constexpr uint32_t kPwmFrequency = 20000;
constexpr uint8_t kPwmBits = 8;
constexpr uint32_t kDuty = 77;  // About 30% duty for the guarded airflow test.
constexpr int kCenterX = 1915;
constexpr int kCenterY = 1925;
constexpr int kDeadzone = 300;

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

enum class Motion { Center, Left, Right, Forward, Unsupported };
enum class State { Disarmed, Armed, Pulsing };

QueueHandle_t commandQueue = nullptr;
State state = State::Disarmed;
Motion activeMotion = Motion::Center;
uint32_t armedAt = 0;
uint32_t pulseStartedAt = 0;

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

void disarm(const char *reason) {
  const bool leftStopped = ledcWrite(kLeftIn1, 0);
  const bool rightStopped = ledcWrite(kRightIn1, 0);
  if (!leftStopped || !rightStopped) haltWithError("ERROR PWM stop failed; outputs forced LOW");
  state = State::Disarmed;
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

Motion stickMotion(const ControlPacket &packet) {
  const int x = static_cast<int>(packet.x) - kCenterX;
  const int y = static_cast<int>(packet.y) - kCenterY;
  if (abs(y) <= kDeadzone) {
    if (x < -kDeadzone) return Motion::Left;
    if (x > kDeadzone) return Motion::Right;
    return Motion::Center;
  }
  if (abs(x) <= kDeadzone && y < -kDeadzone) return Motion::Forward;
  return Motion::Unsupported;
}

void startPulse(Motion motion, uint32_t now) {
  const bool runLeft = motion == Motion::Right || motion == Motion::Forward;
  const bool runRight = motion == Motion::Left || motion == Motion::Forward;
  if (!ledcWrite(kLeftIn1, runLeft ? kDuty : 0) || !ledcWrite(kRightIn1, runRight ? kDuty : 0)) {
    haltWithError("ERROR PWM start failed; outputs forced LOW");
  }
  activeMotion = motion;
  pulseStartedAt = now;
  state = State::Pulsing;
  Serial.printf("PULSE | left=%u right=%u | max 200 ms\n", runLeft ? 1u : 0u, runRight ? 1u : 0u);
}

void setup() {
  for (uint8_t pin : kMotorPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
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
  static bool centered = false;
  static uint32_t centeredAt = 0;
  static uint32_t lastStatus = 0;
  ReceivedCommand incoming{};
  if (xQueueReceive(commandQueue, &incoming, 0) == pdTRUE) {
    latest = incoming;
    received = true;
  }
  const uint32_t now = millis();
  const bool fresh = received && now - latest.receivedAt < kLinkTimeoutMs;
  const Motion motion = stickMotion(latest.packet);
  const bool neutral = fresh && !latest.packet.button && motion == Motion::Center;
  if (neutral && !centered) centeredAt = now;
  centered = neutral;
  const int command = Serial.read();

  if (state != State::Disarmed && (command == '0' || !Serial || !fresh || latest.packet.button)) {
    disarm("STOP | disarmed by stop command, button, or connection loss");
  } else if (state == State::Pulsing) {
    if (motion != activeMotion || now - pulseStartedAt >= kPulseMs) disarm("STOP | pulse complete");
  } else if (state == State::Armed) {
    if (now - armedAt >= kArmTimeoutMs || motion == Motion::Unsupported) {
      disarm("STOP | arm expired or unsupported stick direction");
    } else if (motion != Motion::Center) {
      startPulse(motion, now);
    }
  } else if (command == 'A') {
    if (Serial && centered && now - centeredAt >= kCenterHoldMs) {
      state = State::Armed;
      armedAt = now;
      Serial.println("ARMED | one pulse available");
    } else {
      Serial.println("ARM REFUSED | center the stick and check controller link");
    }
  }

  if (state == State::Disarmed && now - lastStatus >= 500) {
    lastStatus = now;
    if (!fresh) Serial.println("READY | DISARMED | waiting for controller");
    else if (neutral && now - centeredAt >= kCenterHoldMs) Serial.println("READY | DISARMED | centered");
    else Serial.println("READY | DISARMED | center the stick");
  }
  delay(1);
}
