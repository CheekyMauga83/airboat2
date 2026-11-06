# Airboat

Two ESP32-S3 N16R8 boards are planned for a joystick controller and a
turbidity-sensing airboat. Start by testing the controller over USB.

## VS Code terminal dashboard

Open this folder in VS Code and use two terminals. Close Arduino Serial Monitor,
the desktop monitor, and any other reader on the controller port first.

Terminal 1 — development:

```sh
cd ~/Documents/ChatGPT/airboat
codex
```

Terminal 2 — verify ports, then start feedback:

```sh
cd ~/Documents/ChatGPT/airboat
python3 tools/controller_terminal.py --list-ports
python3 tools/controller_terminal.py --port /dev/cu.usbmodem101
```

Use the port whose USB serial number matches controller `E0:72:A1:D5:25:90`.
The recorded boat is `/dev/cu.usbmodem1101`, serial `44:1B:F6:FE:71:A8`.
Ports may change after reconnecting. Expand terminal 2 to at least 96 columns
and 37 rows (narrow terminals stack panels and need 55 rows) for the full cyan/green dashboard. Ctrl+C (or Q) quits and releases
the port. Connection errors include recovery instructions; disconnected or
stale readings never display as live. Restart the viewer after reconnecting.

The dashboard shows X/Y, button, proposed left/right motor duty and voltage,
measured serial sample rate, data age, joystick position, and recent serial lines.
Motor estimates use observed centers, a provisional 5% dead zone, and an assumed
7 V rail. They are not applied outputs or measured motor speeds; RPM is unknown.
Use `--motor-voltage`, `--center-x`, `--center-y`, and `--deadzone` to adjust the
assumptions. Radio counters remain in the serial log. See [PARK.md](PARK.md) for
the estimation model and the parked computer-control plan.
The water-quality panel is a placeholder: NTU stays blank until a real sensor
feed and calibration are implemented. No turbidity measurements are inferred.
It polls serial roughly every 2 ms and redraws at up to 60 FPS, processing
every complete input line. Actual rates depend on terminal and host load. Existing controller
firmware prints approximately four times per second and transmits at up to
20 packets per second; faster redraws do not create extra hardware readings.
Raw axes remain uncalibrated. MAC_ACK confirms radio delivery, while boat
LINK OK confirms application receipt. Keep the motor supply disconnected.
The viewer sends no serial commands and requires only Python's standard curses
module and the existing pyserial installation on this Mac.

Preview the interface without opening USB:

```sh
python3 tools/controller_terminal.py --demo
```

Demo mode is visibly labeled simulated. The dashboard/parser were checked locally,
but this Codex sandbox denied opening USB, so live controller feedback still needs
verification by running the command above in VS Code terminal 2.

## Desktop controller monitor

Double-click `Open Controller Monitor.command` to open the local desktop
interface, then select the controller port (recorded as `/dev/cu.usbmodem101`)
and click **Connect**. Close any other serial monitor using that same port first.
The interface displays raw X/Y position, button state, sequence, MAC ACK and
failure counters, plus the serial log. Values are marked stale after two seconds
without readings. It reads existing diagnostics and sends no serial commands.
MAC ACK indicates radio delivery, not boat application receipt.

Alternatively run `python3 tools/controller_monitor.py` from this directory.
Requires Python with Tk and `pyserial`; both were available in the local
Homebrew Python when the monitor was added. No firmware upload is needed.

## Controller joystick test

Open `firmware/controller_joystick_test/controller_joystick_test.ino` in Arduino IDE.
Connect only the controller board by USB for this test.

| Joystick | Controller ESP32-S3 |
| --- | --- |
| VCC (may be labeled +5V) | 3V3 |
| GND | GND |
| VRx | GPIO4 |
| VRy | GPIO5 |
| SW | GPIO6 |

Install **esp32 by Espressif Systems** in Boards Manager. This sketch is compiled
with Arduino-ESP32 3.3.11 and these settings:

- Board: ESP32S3 Dev Module
- Flash Size: 16MB (128Mb)
- PSRAM: OPI PSRAM (N16R8)
- USB Mode: Hardware CDC and JTAG
- USB CDC On Boot: Enabled
- Upload Mode: UART0 / Hardware CDC
- Port: the controller's USB serial port

Use the board's native USB connector for these CDC settings. If it has a separate
USB-to-UART connector, its upload/monitor configuration can differ.

Upload, then open Serial Monitor at **115200 baud**. If upload cannot connect,
hold BOOT, press and release RESET, release BOOT, and select the serial port again.
If necessary press RESET after uploading and reselect the port for Serial Monitor.

The sketch prints ten readings per second, averaging 16 samples per axis:

```text
X=2100  Y=2080  BUTTON=released
```

The numbers above are illustrative. Record actual values for:

| Stick position | X | Y |
| --- | --- | --- |
| Center | | |
| Full left | | |
| Full right | | |
| Full forward | | |
| Full backward | | |

Raw readings range from 0 to 4095. Center is not assumed to be exactly 2000;
ADC variation and saturation near the supply rails are possible. Confirm that
each axis changes smoothly and note whether its direction matches the intended
controls. Pressing the stick should change BUTTON to PRESSED. This diagnostic
does not calibrate axes or debounce the button.

## Recorded boat wiring

Left and right are viewed from behind the boat looking forward.

| Function | Boat ESP32-S3 GPIO |
| --- | --- |
| Left DRV8871 IN1 | 15 |
| Left DRV8871 IN2 | 16 |
| Right DRV8871 IN1 | 13 |
| Right DRV8871 IN2 | 14 |
| Turbidity divider junction | 4 |

DFRobot SEN0189 analog output connects through 10 kOhm to GPIO4, with 20 kOhm
from that junction to common ground. Set the sensor module to analog (A) mode.
Its documented 0-4.5 V output becomes 0-3.0 V at this divider.

The planned electronics rail is 5 V from the LM2596. The proposed motor-driver
rail is 7 V from the separate buck-boost converter. Actual powered rail checks,
DRV8871 current limits, motor PWM settings, motor heating, and thrust remain
unverified. The measured resistor value near 97 kOhm has not been confirmed as
the ILIM resistance; do not treat a calculated 0.66 A limit as established.
The `firmware/boat_link_test/boat_link_test.ino` sketch is an ESP-NOW receive-only
diagnostic. It holds all four driver control pins LOW while running and never
drives motors. Keep the battery disconnected for this USB test. It listens on
channel 1 for 16-byte version-1 packets from controller MAC E0:72:A1:D5:25:90,
prints received raw joystick values, and reports link loss after 500 ms without
a valid packet. Its matching transmitter is
`firmware/controller_link_test/controller_link_test.ino`, using the same Arduino
board settings as the joystick test. The transmitter sends raw X/Y and button
state up to 20 times per second to boat MAC 44:1B:F6:FE:71:A8. It checks that it
is running on controller E0:72:A1:D5:25:90 before transmitting. MAC_ACK counts
radio-layer delivery reports; the boat's LINK OK output confirms application
receipt. This bench diagnostic uses unencrypted ESP-NOW on channel 1. It does
not yet calibrate, invert, or mix joystick commands for motor control.
The boat was identified as MAC 44:1B:F6:FE:71:A8. No operational motor-control
firmware is included yet.

## References

- [Espressif Arduino ADC API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html)
- [Espressif USB CDC setup](https://docs.espressif.com/projects/arduino-esp32/en/latest/tutorials/cdc_dfu_flash.html)
- [DFRobot SEN0189](https://wiki.dfrobot.com/sen0189)
- [TI DRV8871 datasheet](https://www.ti.com/lit/ds/symlink/drv8871.pdf)
