#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <cstring>

// controller_link_test + turbidity relay. Joystick reading and transmission
// are unchanged. Addition: 16-byte telemetry packets from the boat are
// received and printed over USB as "TURB adc=<0-4095> mv=<GPIO4 millivolts>
// n=<boat sequence>". Pair with boat_l298_joystick_telemetry. The verified
// controller_link_test sketch is unchanged.
constexpr uint8_t kJoystickX = 4;
constexpr uint8_t kJoystickY = 5;
constexpr uint8_t kJoystickButton = 6;
constexpr uint8_t kChannel = 1;
constexpr uint8_t kBoatMac[] = {0x44, 0x1b, 0xf6, 0xfe, 0x71, 0xa8};
constexpr uint8_t kControllerMac[] = {0xe0, 0x72, 0xa1, 0xd5, 0x25, 0x90};
constexpr uint32_t kPacketMagic = 0x41495242;

// Must match boat_link_test: 16 bytes, little endian; axes remain raw.
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

constexpr uint32_t kTelemetryMagic = 0x41495254;

// Boat -> controller. Must match boat_l298_joystick_telemetry; little endian.
// The last three bytes carry the boat's applied left/right duty and armed flag;
// this sketch does not print them yet.
struct TelemetryPacket {
  uint32_t magic;
  uint32_t sequence;
  uint16_t adc;
  uint16_t millivolts;
  uint8_t version;
  uint8_t reserved[3];
};
static_assert(sizeof(TelemetryPacket) == 16, "Unexpected telemetry layout");

QueueHandle_t sendResultQueue = nullptr;
QueueHandle_t telemetryQueue = nullptr;

void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int length) {
  if (!info || !data || length != sizeof(TelemetryPacket) ||
      memcmp(info->src_addr, kBoatMac, sizeof(kBoatMac)) != 0) {
    return;
  }
  TelemetryPacket telemetry{};
  memcpy(&telemetry, data, sizeof(telemetry));
  if (telemetry.magic != kTelemetryMagic || telemetry.version != 1 || telemetry.adc > 4095) {
    return;
  }
  // Wi-Fi task: copy and return; loop() does the printing.
  xQueueOverwrite(telemetryQueue, &telemetry);
}

void onSent(const esp_now_send_info_t *, esp_now_send_status_t status) {
  // Report from loop(), not from the high-priority Wi-Fi callback.
  xQueueOverwrite(sendResultQueue, &status);
}

uint16_t readAxis(uint8_t pin) {
  uint32_t sum = 0;
  for (uint8_t i = 0; i < 16; ++i) sum += analogRead(pin);
  return static_cast<uint16_t>((sum + 8) / 16);
}

void haltWithError(const char *message) {
  while (true) {
    Serial.println(message);
    delay(1000);
  }
}

void setup() {
  Serial.begin(115200);
  // USB diagnostics must never hold up the radio when no host is reading.
  Serial.setTxTimeoutMs(0);
  pinMode(kJoystickX, INPUT);
  pinMode(kJoystickY, INPUT);
  pinMode(kJoystickButton, INPUT_PULLUP);
  analogReadResolution(12);
  analogSetPinAttenuation(kJoystickX, ADC_11db);
  analogSetPinAttenuation(kJoystickY, ADC_11db);
  sendResultQueue = xQueueCreate(1, sizeof(esp_now_send_status_t));
  if (!sendResultQueue) haltWithError("ERROR: send queue allocation failed");
  telemetryQueue = xQueueCreate(1, sizeof(TelemetryPacket));
  if (!telemetryQueue) haltWithError("ERROR: telemetry queue allocation failed");
  if (!WiFi.mode(WIFI_STA)) haltWithError("ERROR: Wi-Fi start failed");
  uint8_t mac[6]{};
  if (esp_wifi_get_mac(WIFI_IF_STA, mac) != ESP_OK) {
    haltWithError("ERROR: could not read station MAC");
  }
  if (memcmp(mac, kControllerMac, sizeof(mac)) != 0) {
    haltWithError("ERROR: this sketch belongs on controller E0:72:A1:D5:25:90");
  }
  if (esp_wifi_set_channel(kChannel, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
    haltWithError("ERROR: channel setup failed");
  }
  if (esp_now_init() != ESP_OK) haltWithError("ERROR: ESP-NOW initialization failed");
  if (esp_now_register_send_cb(onSent) != ESP_OK) {
    haltWithError("ERROR: send callback setup failed");
  }
  // Telemetry is optional: a failed registration must not stop joystick TX.
  esp_now_register_recv_cb(onReceive);
  esp_now_peer_info_t peer{};
  memcpy(peer.peer_addr, kBoatMac, sizeof(kBoatMac));
  peer.channel = kChannel;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) haltWithError("ERROR: boat peer setup failed");
  if (Serial && Serial.availableForWrite() >= 128) {
    Serial.printf("CONTROLLER LINK+TELEMETRY TEST | MAC=%02X:%02X:%02X:%02X:%02X:%02X | channel=%u\n",
                  mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], kChannel);
  }
}

void loop() {
  static ControlPacket packet{kPacketMagic, 0, 0, 0, 0, 1, 0};
  static bool pending = false;
  static uint32_t lastSend = 0;
  static uint32_t lastPrint = 0;
  static uint32_t delivered = 0;
  static uint32_t failed = 0;
  esp_now_send_status_t status;
  if (xQueueReceive(sendResultQueue, &status, 0) == pdTRUE) {
    pending = false;
    if (status == ESP_NOW_SEND_SUCCESS) ++delivered;
    else ++failed;
  }
  const uint32_t now = millis();
  // At most 20 packets/s; wait for completion before submitting another.
  if (!pending && now - lastSend >= 50) {
    lastSend = now;
    packet.x = readAxis(kJoystickX);
    packet.y = readAxis(kJoystickY);
    packet.button = digitalRead(kJoystickButton) == LOW ? 1 : 0;
    ++packet.sequence;
    pending = true;
    if (esp_now_send(kBoatMac, reinterpret_cast<const uint8_t *>(&packet),
                     sizeof(packet)) != ESP_OK) {
      pending = false;
      ++failed;
    }
  }
  if (now - lastPrint >= 250 && Serial && Serial.availableForWrite() >= 192) {
    lastPrint = now;
    Serial.printf("TX seq=%lu X=%u Y=%u BUTTON=%s MAC_ACK=%lu FAIL=%lu pending=%u\n",
                  static_cast<unsigned long>(packet.sequence),
                  static_cast<unsigned>(packet.x), static_cast<unsigned>(packet.y),
                  packet.button ? "PRESSED" : "released",
                  static_cast<unsigned long>(delivered),
                  static_cast<unsigned long>(failed), pending ? 1 : 0);
  }
  TelemetryPacket telemetry;
  if (xQueueReceive(telemetryQueue, &telemetry, 0) == pdTRUE && Serial &&
      Serial.availableForWrite() >= 64) {
    Serial.printf("TURB adc=%u mv=%u n=%lu\n", static_cast<unsigned>(telemetry.adc),
                  static_cast<unsigned>(telemetry.millivolts),
                  static_cast<unsigned long>(telemetry.sequence));
  }
  delay(2);
}
