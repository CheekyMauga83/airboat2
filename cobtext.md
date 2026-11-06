# Airboat project context

Updated 2026-11-06. This retains the requested filename `cobtext.md`.

## Goal and scope

Build a joystick-controlled airboat with two ESP32-S3 N16R8 boards, differential
motor control, and a DFRobot SEN0189 turbidity sensor. The owner plans to work
with another engineer and wants the code and project context in
https://github.com/CheekyMauga83/airboat2 (current upload destination).
The original shared repository was Pipemedeiros/AIRBOAT.

Use the existing purchased parts where possible. The owner explicitly excluded
TDS and temperature sensors. The latest wiring decisions and measured joystick
behavior supersede earlier proposals.

## Recorded hardware

- Controller and boat: ESP32-S3 N16R8, configured as ESP32S3 Dev Module with
  16 MB flash, OPI PSRAM, native USB CDC, Arduino-ESP32 3.3.11.
- Controller station MAC E0:72:A1:D5:25:90; recorded USB /dev/cu.usbmodem101.
- Boat station MAC 44:1B:F6:FE:71:A8; recorded USB /dev/cu.usbmodem1101.
  Rediscover ports after reconnecting; serial diagnostics use 115200 baud.
- Joystick: 3V3 supply, common GND, VRx GPIO4, VRy GPIO5, switch GPIO6 on controller.
- Two DRV8871 brushed-motor drivers. Viewed from behind the boat looking forward:
  left IN1 GPIO15 / IN2 GPIO16; right IN1 GPIO13 / IN2 GPIO14.
- Purchased motors were described as AEDIKO 716 coreless 3.7 V brushed motors,
  7 x 16 mm, with 75 mm CW/CCW propellers. Advertised RPM is not measured RPM.
- LM2596 is assigned to the planned 5 V electronics/sensor rail. A separate
  BGTXINGI buck-boost module marketed as 8 A is assigned to the proposed 7 V
  motor-driver rail. Listing current claims are not verified continuous ratings.
- SEN0189 analog output passes through 10 kOhm to boat GPIO4, with 20 kOhm
  from that junction to common ground. Recorded divider ratio is 2/3.
- Ground bus continuity was checked in the hardware session after correcting
  ESP32 GND to connect directly to common ground. Recorded checks are historical,
  not a guarantee of the current physical wiring.
- Battery specifications, loaded rail behavior, motor current and thermal limits,
  and usable thrust remain to be established. A reading near 97 kOhm was not
  confirmed as the DRV8871 ILIM resistance.

## Bench results and current firmware

The joystick USB programming and directed input tests passed. Observed rest is
approximately X=1915, Y=1925. Left X is near 0, right X=4095; forward Y is near
0, backward Y=4095. The button reports released/PRESSED. This measured Y mapping
supersedes the original increasing-Y-forward proposal. Raw axes are uncalibrated.

The matching controller/boat ESP-NOW diagnostics compiled and uploaded. They use
16-byte version-1 packets on channel 1, currently unencrypted. Controller sends
at up to 20 Hz and prints around 4 Hz. MAC_ACK is radio delivery; boat LINK OK
confirms application receipt. Direction/button transmission, link-loss detection,
and automatic reconnect after controller power cycling passed the bench checks.
A USB logging dependency was fixed so transmission continues with its serial
monitor closed. See docs/controller-test.md and docs/wireless-test.md for evidence.

Boat firmware is receive-only and holds GPIO15/16/13/14 LOW. No operational motor
control, powered motor stopping, calibrated turbidity telemetry, or water test
has been established. Preserve diagnostic firmware during interface work.

## Feedback tools and final interface requirements

The owner wants VS Code with two terminals: Codex in one, a visible serial
feedback viewer in the other. Close other readers of the controller port.

```sh
# Terminal 1, from the project directory
codex
# Terminal 2, from the project directory
python3 tools/controller_terminal.py --list-ports
python3 tools/controller_terminal.py --port /dev/cu.usbmodem101
```

`tools/controller_monitor.py` and `Open Controller Monitor.command` provide the
earlier Tk desktop viewer. Desktop launch exited with code 134 in the prior
session, and that session could not open USB. The terminal viewer is the chosen
workflow. Local parser/layout checks were reported, but live viewer operation
must not be claimed verified without actual controller output.

Final preference: simple essential labels, cyan/green styling, joystick position
and button, turbidity placeholder, motor estimates, status and serial log.
Remove decorative mission-control wording. Retain sequence/MAC_ACK/FAIL/pending
information in the raw log. Poll about every 2 ms and draw at up to 60 FPS;
actual new coordinates remain limited by the unchanged firmware's roughly 4 Hz
serial output. Full layout needs 96 columns by 37 rows; narrow layout needs 55 rows.
Ctrl+C or Q quits. Stale data is marked after two seconds. Demo mode is explicitly
simulated and does not open USB. Turbidity remains -- NTU until real measurements
and calibration exist.

Motor estimate replaces the former Radio card. Normalize axes around observed
centers, apply provisional 5% dead zone, use forward=-Y and turn=+X, mix
left=forward+turn and right=forward-turn, then proportionally limit both to [-1,1].
Show estimated signed duty and ideal average voltage using an assumed 7 V rail.
These are not applied outputs, measured speed, thrust, or RPM. RPM stays unknown.
Hide estimates for stale/disconnected samples. Calibration options are documented
in README.md and PARK.md.

## Parked work and remaining validation

PARK.md contains the reproducible visual specification, formulas, computer-control
requirements, and monitoring-app proposal. The proposed app starts with a single
USB-owning bridge, connection controls, telemetry, timestamps, recording/replay,
and CSV export. Computer actuation requires new command and motor firmware,
explicit arm/disarm, manual override, bounded commands, acknowledgments, secure
pairing, boat watchdogs, and a physical cutoff. It is not implemented.

Remaining stages recorded in the hardware session: verify supplies unloaded and
under load; establish motor/PWM/current/thermal behavior; calibrate turbidity;
integrate motors and sensor while checking noise/resets and real stopping; then
perform supervised tethered flotation, thrust, steering, and range tests.

## Source map and upload request

- README.md: setup, wiring and usage.
- docs/controller-test.md and docs/wireless-test.md: bench evidence.
- docs/feedback-session-context.md: relevant desktop/terminal feedback requests
  and responses, including the request to save the design and upload the folder.
- PARK.md: design replication and future app/computer-control plan.
- firmware/: three diagnostic sketches.
- tools/: desktop viewer, terminal viewer and generated local caches (ignored).

The owner authorized uploading all project files, including PARK.md and this
context document. Preserve unrelated remote work. Before this request, files
were staged but no local commit or successful GitHub upload existed. The original GitHub
connector could not access Pipemedeiros/AIRBOAT. The owner subsequently requested
a new airboat2 repository under CheekyMauga83, and connector write access to that
repository was verified. The requested full project snapshot is being saved there. Credentials are not project context
and must never be placed in this repository.
