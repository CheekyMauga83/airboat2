#include <Arduino.h>
#include <cstring>

// USB-only bench test: remove BOTH propellers. No joystick or radio commands.
// Firmware limits are not a guarantee that 7 V pulses are safe for a 3.7 V motor.
constexpr uint8_t pins[] = {15, 16, 17, 14}; // left IN1/IN2, right IN1/IN2
constexpr uint32_t runMs = 2000, heartbeatMs = 400, cooldownMs = 5000;
int pwmPin = -1;
bool active = false, hasRun = false, hasHeartbeat = false;
uint32_t started = 0, heartbeat = 0, stopped = 0;
uint32_t expectedTicks = 0, expectedHz = 0;
char line[80];
size_t used = 0;
bool discardLine = false;

void allLow() {
  if (pwmPin >= 0) ledcDetach(pwmPin);
  pwmPin = -1;
  for (uint8_t pin : pins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
}

void stop(const char *reason) {
  allLow();
  if (active) { stopped = millis(); hasRun = true; }
  active = false;
  Serial.printf("STOP %s\n", reason);
}

void command(const char *s) {
  if (!strcmp(s, "STOP")) { stop("requested"); return; }
  if (!strcmp(s, "PING")) { heartbeat = millis(); hasHeartbeat = true; return; }
  if (!strcmp(s, "INFO")) {
    Serial.printf("AIRBOAT_DIAG_V1 active=%d left=15,16 right=17,14 duration_ms=2000 cap=50%%\n", active);
    return;
  }
  char side, mode, extra;
  unsigned hz, percent;
  if (sscanf(s, "RUN %c %c %u %u %c", &side, &mode, &hz, &percent, &extra) != 4 ||
      (side != 'L' && side != 'R') || (mode != 'C' && mode != 'B') ||
      (hz != 1000 && hz != 20000) || (percent != 25 && percent != 50)) {
    stop("invalid_command");
    return;
  }
  if (active) { stop("run_while_active_rejected"); return; }
  if (hasRun && millis() - stopped < cooldownMs) {
    Serial.println("REJECT cooldown_5_seconds"); return;
  }
  if (!hasHeartbeat || millis() - heartbeat >= heartbeatMs) {
    Serial.println("REJECT fresh_PING_required"); return;
  }
  allLow();
  const int in1 = pins[side == 'L' ? 0 : 2];
  const int in2 = pins[side == 'L' ? 1 : 3];
  const uint32_t driveTicks = percent == 25 ? 64 : 128;
  // C: drive/coast = PWM IN1, IN2 LOW. B: drive/brake = IN1 HIGH,
  // PWM IN2; IN2 LOW drives, IN2 HIGH brakes. Same forward polarity.
  pwmPin = mode == 'C' ? in1 : in2;
  expectedTicks = mode == 'C' ? driveTicks : 256 - driveTicks;
  expectedHz = hz;
  if (!ledcAttach(pwmPin, hz, 8) || !ledcWrite(pwmPin, expectedTicks)) {
    stop("pwm_setup_failed"); return;
  }
  // Wait for the initial PWM duty to latch before enabling the fixed HIGH.
  delayMicroseconds(1100);
  const uint32_t readHz = ledcReadFreq(pwmPin);
  if (ledcRead(pwmPin) != expectedTicks || readHz != hz) {
    stop("pwm_register_mismatch"); return;
  }
  started = millis();
  active = true;
  if (mode == 'B') digitalWrite(in1, HIGH);
  Serial.printf("START side=%c mode=%c hz=%lu drive_percent=%u pwm_pin=%d register_ticks=%lu/256 duration_ms=%lu\n",
    side, mode, (unsigned long)readHz, percent, pwmPin,
    (unsigned long)ledcRead(pwmPin), (unsigned long)runMs);
  Serial.println("NOTE register_readback_is_not_measured_voltage_or_current");
}

void setup() {
  allLow();
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
}

void loop() {
  if (active) {
    if (millis() - started >= runMs) stop("time_limit");
    else if (!Serial || millis() - heartbeat >= heartbeatMs) stop("USB_heartbeat_lost");
    else if (ledcRead(pwmPin) != expectedTicks || ledcReadFreq(pwmPin) != expectedHz)
      stop("pwm_register_changed");
  }
  // Bounded parser work keeps stop checks responsive even under serial flooding.
  for (int i = 0; i < 32 && Serial.available(); ++i) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!discardLine && used) { line[used] = 0; command(line); }
      used = 0; discardLine = false;
    } else if (!discardLine) {
      if (used < sizeof(line) - 1) line[used++] = c;
      else { used = 0; discardLine = true; stop("line_too_long"); }
    }
  }
  delay(1);
}
