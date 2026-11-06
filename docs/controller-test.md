# Controller joystick USB test — 2026-11-06

Sketch: `firmware/controller_joystick_test/controller_joystick_test.ino`

Compiled with Arduino-ESP32 3.3.11 for ESP32S3 Dev Module, 16 MB flash,
OPI PSRAM, and hardware USB CDC. Upload succeeded and esptool verified the
written data. The board needed a physical RESET after upload; reopening the
serial monitor then produced live readings at 115200 baud.

Connected chip identified as ESP32-S3 revision v0.2 with 8 MB embedded PSRAM.

| Check | Observed result |
| --- | --- |
| X (GPIO4), stick at rest | Approximately 1915 |
| Y (GPIO5), stick at rest | Approximately 1925 |
| X during movement | Directed left hold: approximately 0; directed right hold: 4095 |
| Y during movement | Directed forward hold: approximately 0; directed backward hold: 4095 |
| Button (GPIO6) | Both released and PRESSED observed |

These are raw ADC values, not calibrated 0–4000 control commands. Small rest
variations were observed. Directed tests confirmed left (X approximately 0),
right (X = 4095), forward (Y approximately 0), and backward (Y = 4095). Forward is
opposite the originally proposed increasing-Y mapping; controller firmware
must invert Y when producing forward-positive commands. Center/dead-zone and endpoint
calibration remain for the controller firmware.

This verifies controller USB programming, serial output, both joystick axes,
and button detection. It does not verify ESP-NOW, boat hardware, or motor control.
