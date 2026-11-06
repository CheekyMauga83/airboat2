#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <cstring>

// Wireless diagnostic only. There is deliberately no motor-drive routine.
constexpr uint8_t kMotorPins[] = {15, 16, 13, 14};
constexpr uint8_t kChannel = 1;
constexpr uint8_t kControllerMac[] = {0xe0, 0x72, 0xa1, 0xd5, 0x25, 0x90};
constexpr uint32_t kPacketMagic = 0x41495242;
constexpr uint32_t kTimeoutMs = 500;

// Wire format for the matching controller_link_test sketch; little endian.
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

void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (!info || !data || length != sizeof(ControlPacket) ||
      memcmp(info->src_addr, kControllerMac, sizeof(kControllerMac)) != 0) {
    return;
  }
  ReceivedCommand command{};
  memcpy(&command.packet, data, sizeof(command.packet));
  const ControlPacket &packet = command.packet;
  if (packet.magic != kPacketMagic || packet.version != 1 ||
      packet.x > 4095 || packet.y > 4095 || packet.button > 1 || packet.reserved != 0) {
    return;
  }
  command.receivedAt = millis();
  // The callback runs on the Wi-Fi task: copy data and return promptly.
  xQueueOverwrite(commandQueue, &command);
}

void haltWithError(const char *message) {
  while (true) {
    Serial.println(message);
    delay(1000);
  }
}

void setup() {
  for (uint8_t pin : kMotorPins) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  Serial.begin(115200);
  const uint32_t started = millis();
  while (!Serial && millis() - started < 3000) {
    delay(10);
  }
  commandQueue = xQueueCreate(1, sizeof(ReceivedCommand));
  if (!commandQueue) haltWithError("ERROR: receive queue allocation failed");
  if (!WiFi.mode(WIFI_STA)) haltWithError("ERROR: Wi-Fi start failed");
  if (esp_wifi_set_channel(kChannel, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
    haltWithError("ERROR: channel setup failed");
  }
  if (esp_now_init() != ESP_OK) haltWithError("ERROR: ESP-NOW initialization failed");
  if (esp_now_register_recv_cb(onReceive) != ESP_OK) {
    haltWithError("ERROR: receive callback setup failed");
  }
  uint8_t mac[6]{};
  if (esp_wifi_get_mac(WIFI_IF_STA, mac) != ESP_OK) {
    haltWithError("ERROR: could not read station MAC");
  }
  Serial.printf("BOAT LINK TEST | MAC=%02X:%02X:%02X:%02X:%02X:%02X | channel=%u | MOTORS DISABLED\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], kChannel);
}

void loop() {
  static ReceivedCommand latest{};
  static bool received = false;
  static uint32_t lastPrint = 0;
  ReceivedCommand incoming{};
  if (xQueueReceive(commandQueue, &incoming, 0) == pdTRUE) {
    latest = incoming;
    received = true;
  }
  const uint32_t now = millis();
  if (now - lastPrint >= 100) {
    lastPrint = now;
    if (!received) {
      Serial.println("WAITING FOR CONTROLLER | MOTORS DISABLED");
    } else if (now - latest.receivedAt >= kTimeoutMs) {
      Serial.println("LINK LOST (>500ms) | MOTORS DISABLED");
    } else {
      Serial.printf("LINK OK | seq=%lu X=%u Y=%u BUTTON=%s | MOTORS DISABLED\n",
                    static_cast<unsigned long>(latest.packet.sequence),
                    static_cast<unsigned>(latest.packet.x),
                    static_cast<unsigned>(latest.packet.y),
                    latest.packet.button ? "PRESSED" : "released");
    }
  }
  delay(5);
}
