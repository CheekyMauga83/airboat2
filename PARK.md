# Computer control idea

Parked proposal, not an implemented control path. The current terminal viewer
only reads serial diagnostics. The current boat firmware holds motor pins LOW.
No firmware was changed for the dashboard estimates.

## Dashboard motor estimates

The Radio panel is replaced by a proposed left/right motor-demand estimate.
It uses observed joystick centers X=1915 / Y=1925 and endpoints 0..4095.
Each side of each axis is normalized separately. A provisional 5% normalized
dead zone is removed and the remaining range rescaled to 0..1. Lower Y means
forward; higher X means right. Proposed mix: left = forward + turn,
right = forward - turn. Both are divided by max(1, abs(left), abs(right))
to preserve their ratio within -100%..100%. Positive means proposed forward.
Turning right therefore proposes a faster left motor. Actual motor polarity,
reverse capability, propeller behavior, and steering must be verified.

Percentages are proposed signed PWM duty demands, not physical motor speed.
Displayed volts are duty times an explicitly assumed rail (default 7 V), an
ideal signed average-voltage approximation, not measured motor voltage.
Driver drops, PWM mode, current limiting, back EMF, motor load, and propeller
behavior are not modeled. RPM, thrust, and boat speed cannot be inferred
reliably without measurements. Even a nonzero estimate does not mean a motor
is running. Stale/disconnected input hides estimates instead of showing zero.
The raw serial log retains the radio counters.

Optional viewer arguments:

```sh
python3 tools/controller_terminal.py --port /dev/cu.usbmodem101 \
  --motor-voltage 7 --center-x 1915 --center-y 1925 --deadzone 0.05
```

The voltage flag supplies an assumption; replace it with a measured rail value
when available. Center, dead zone, motor starts/stops, direction, and end stops
need proper calibration before these formulas become motor-control code.

## What computer control needs

- A single local process owning the controller serial port, forwarding telemetry
  to the interface and accepting commands. This avoids competing serial monitors.
  The current Codex sandbox cannot open USB; the bridge must run on the host with
  USB access. Use a loopback-only authenticated API or another explicitly
  authorized connection to expose it to an agent when available.
- A simple interface for computer use: connect, status, explicit arm/disarm,
  bounded throttle/steering, stop, and telemetry. Prefer structured commands for
  automation. UI clicks can request actions; the ESP32 must handle timing.
- New controller firmware that accepts versioned USB commands and arbitrates
  between physical joystick and computer input. Manual override and STOP take
  priority. Button actions must be specified; no existing button is assumed to arm.
- A documented command schema with command ID, sequence, mode, bounded values,
  session identity, expiry, and validation. Reject malformed, duplicate, expired,
  and out-of-order commands. Return accepted/rejected state and reason.
- Boat motor-control firmware with verified GPIO mapping (left 15/16, right
  13/14), PWM mode/frequency, polarity, ramp limits, reversal handling, neutral
  startup, and bounded duty. Keep current receive-only diagnostics available.
- Stop on expired commands, radio loss, USB/bridge failure, restart, and disarm.
  Enforce the watchdog on the boat, independent of the computer. Start from the
  diagnostic 500 ms loss threshold and validate the final timeout experimentally.
  Require explicit re-arming after faults; never resume a cached command.
- A local physical power cutoff and operator-controlled arming during testing.
  A UI stop alone cannot stop hardware after a communication failure.
- Boat acknowledgments reporting applied outputs, arm/fault state, and command ID.
  MAC_ACK is only radio delivery; application receipt is not proof of motor output.
  Add motor rail sensing, current sensing, and RPM sensing if real speed estimates
  or fault detection are required. Define units and sample timestamps.
- Secure the control link before enabling computer actuation. Current bench
  ESP-NOW packets are unencrypted; add authenticated pairing/control and reject
  unintended senders/replays. Local bridge access must also be restricted.

## Measurements and validation before actuation

Record actual motor rail under load, motor specifications, confirmed DRV8871
ILIM resistance/current limit, motor direction, PWM response, heating, and safe
current draw. The previously measured ~97 kOhm is not confirmed as ILIM.
Build measured duty/voltage/RPM curves under representative propeller loads;
keep RPM unavailable until supported by those measurements or an RPM sensor.

First test parser, mixing, limits, arbitration, and watchdogs with simulated
commands and motors unpowered. Verify physical cutoff and timeout behavior
before restrained, supervised low-duty powered tests. Do not enable unattended
operation as part of this parked idea.

## Turbidity and update rates

Turbidity remains a placeholder. Add SEN0189 sampling on the boat, preserve the
recorded divider, validate actual ADC voltage, calibrate against reference
samples, and send raw ADC, voltage, calibrated NTU, validity, and timestamps.
Never render invented NTU as measured data.

The viewer polls about every 2 ms and draws at up to 60 FPS. Existing controller
firmware prints about 4 Hz and transmits at up to 20 Hz. Faster actual coordinates
require a separate firmware change and upload; keep USB prints nonblocking and
verify radio timing and reconnect behavior after any change.

## Replicating the terminal design

The reproducible implementation is `tools/controller_terminal.py` (Python curses
and pyserial). Install Python 3 and pyserial on a platform with curses support;
on this Mac the dependency is already installed. Run from the repository root:

```sh
python3 -m pip install pyserial
python3 tools/controller_terminal.py --demo
python3 tools/controller_terminal.py --list-ports
python3 tools/controller_terminal.py --port /dev/cu.usbmodem101
```

Visual specification:

- Plain title `Airboat`, subtitle `Controller feedback`, serial port and baud.
- Cyan headings and thin ASCII borders; green fresh data, yellow stale data or
  assumptions, red connection failures. Use the terminal's default background.
- Status line: connection state, observed sample rate, last-sample age, quit key.
- At 96+ columns: left joystick card (46 columns), right turbidity and motor
  estimate cards; below these, the last six serial lines. Minimum full layout
  is 96 columns by 37 rows. Narrow windows stack cards and need 55 rows.
- Joystick card: raw X/Y, button state, 29-by-7 position grid (`@` marker),
  forward at top, backward at bottom, raw-axis endpoint labels.
- Turbidity card: `-- NTU`, no sensor data, calibration pending. Never animate
  a fake measurement. Motor card: signed L/R duty and ideal voltage estimates,
  assumed rail, RPM unknown, explicit `not applied` label.
- Poll serial about every 2 ms; draw at up to 60 FPS. Preserve fragmented lines
  between reads, process complete lines, retain the latest sample. Mark samples
  stale after two seconds and hide motor estimates on stale/disconnected input.
- Ctrl+C or Q exits and closes serial. Demo is visibly labeled simulated and
  never opens USB. No control writes occur in this viewer.

Use the source as the layout reference rather than recreating from a screenshot.
Keep telemetry parsing and estimation semantics when porting to another UI.

## Monitoring app proposal

Build a dedicated local app with the same simple panels and a single serial
bridge that owns USB. First version is monitoring only: port discovery with MAC
identity, connect/disconnect, joystick position/button, diagnostics, actual
sample timestamps, turbidity placeholder, and clearly separated motor estimates.
Add recording/replay and CSV export with units, timestamps, connection events,
and explicit simulated/stale/estimated flags. Support resizing and keyboard use.
A local browser UI can consume a loopback API/WebSocket from the bridge; choose
an app framework when implementing, not as a prerequisite for this design.

Later add real boat telemetry (voltage, current, applied PWM, calibrated turbidity,
and RPM when available). Add control only after the command protocol, arming,
manual override, watchdog, physical cutoff, and validation above are implemented.
Expose connection state and command acceptance/application separately. Never
label estimates as measured speed or treat a UI connection as permission to arm.

## Context document

`cobtext.md` is reserved for the fuller project context to be written later.
Keep existing README and docs as the current source of recorded hardware facts.
