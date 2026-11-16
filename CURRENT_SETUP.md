# Current setup — 2026-11-16

Repository: https://github.com/CheekyMauga83/airboat2

## Resume on another computer

Clone this repository, or pull main in an existing clean checkout. Install Arduino
IDE and **esp32 by Espressif Systems 3.3.11**. Open the sketch matching the board:

- Boat: `firmware/boat_l298_joystick/boat_l298_joystick.ino`.
- Controller: `firmware/controller_link_test/controller_link_test.ino`.
- Optional isolated L298 bench test: `firmware/boat_l298_diagnostic/boat_l298_diagnostic.ino`.

Select ESP32S3 Dev Module, 16 MB flash, OPI PSRAM, Hardware CDC and JTAG,
USB CDC On Boot enabled. Serial monitor: 115200 baud.
CLI FQBN: `esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,USBMode=hwcdc,CDCOnBoot=cdc`.
Python monitors require `python3 -m pip install pyserial`; desktop monitor also
requires Tk. Serial port names change between computers/reconnections.
Boat USB serial/MAC: 44:1B:F6:FE:71:A8. Controller: E0:72:A1:D5:25:90.
Do not upload a boat sketch to the controller or vice versa.

## Installed L298N connections

Left/right viewed from behind boat looking forward. Left motor OUT3/OUT4;
right motor OUT1/OUT2. IN1=GPIO15, IN2=GPIO16, IN3=GPIO17, IN4=GPIO14.
ENA/ENB jumpers installed. 5V-EN regulator jumper REMOVED.
8 A converter OUT+ at 6.0 V feeds motor supply terminal labeled 12V.
Converter OUT−, L298 GND, ESP32 GND and LM2596 GND share ground.
LM2596 regulated 5 V feeds L298 logic 5V and turbidity sensor.
While USB powers boat ESP32, its external 5V/VIN feed is disconnected and
insulated. Do not reconnect external 5 V alongside USB without checking board
power isolation. Disconnect battery before wiring or uploading. Initial motor
tests are propeller-off. Do not apply the old DRV8871 instructions to L298N.

## Current firmware and evidence

Latest boat upload: L298 joystick with 50% maximum duty at 1 kHz, drive/brake.
Click and release centered joystick to arm; click again to disarm. Three-second
continuous drive cutoff; center stick to resume. 150 ms radio timeout disarms.
Starts disarmed. Centers X=1915/Y=1925, deadzone=300; physical forward maps to
lower Y in current controller setup. Reverse joystick does not reverse motors.

Both motors ran strongly and similarly at 25% in separate L298 tests. User
measured right 0.93 V and left 0.94 V DC across outputs. Some USB diagnostic
runs ended early on heartbeat loss; successful full runs also recorded.
At 50%, user reports 1.5 V. These are meter readings of PWM, not peak-voltage,
current, thrust, RPM or thermal validation. 75% was discussed but NOT implemented.
Motors are 3.7 V 716 coreless. The 6 V supply and L298 voltage loss do not ensure
safe motor voltage at higher duty. Propeller-loaded endurance remains unverified.

## Turbidity

SEN0189: 5 V supply, switch A. Signal through 10k to boat GPIO4; 20k from GPIO4
 to ground. Firmware reports raw ADC, ADC millivolts and estimated sensor voltage
(divider correction 1.5), twice per second. NTU remains uncalibrated.
Air initially ~3.09 V; clear water ~4.30 V; cloudy sample ~0.31–0.47 V.
Air recovered ~3.11 V; subsequent clear-water readings varied with placement and
baseline recovery was NOT established. User deferred further bucket tests.
Probe top and connector must remain dry. Controller dashboard still has a
placeholder; actual sensor readings appear on boat USB.

## Previous driver investigation

DRV8871 setup was weak despite ~7 V measured supply; motor output readings
~0.175–0.36 V, varying with PWM. Motors ran strongly directly at 3.7 V.
Right driver was modified with 47k across original 303 (30k); measured ~19k.
No improvement was observed. Root cause was never proven. Do not assume that
modification is safe or that current limiting was confirmed. Old sketches and
notes are retained for history, not the current L298 wiring or upload target.

## Remaining work

Verify joystick direction and failsafe operation on installed L298 setup,
propeller direction, loaded motor current/temperature, supply stability, and
repeatable turbidity response. No calibrated NTU or drinking-water claims.
