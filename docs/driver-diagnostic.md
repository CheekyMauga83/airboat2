# Driver output collapse: controlled bench diagnosis

## What is known

User reports about 6 V unloaded and about 0.2 V with the motor connected, with
about 7 V at the driver's supply screws. The latest message says **0.2 mV**;
confirm the displayed unit on the next run. These are different by 1000 times.
IN1 measured about 1.6 V average and IN2 near zero during the previous PWM test.
Both motors reportedly run much faster directly from 3.7 V.

These observations establish load-dependent behavior, not the cause. An unloaded
drive/coast output can float between pulses: its meter reading is not a prediction
of loaded motor voltage. The current-limit threshold, fast supply dips, output
waveform and motor startup current have not been measured.

## New tools

- `firmware/boat_driver_diagnostic/boat_driver_diagnostic.ino`: USB-only, one driver
  at a time; left IN1/IN2 = GPIO15/16, right = GPIO17/14. No joystick mixing/radio.
- `tools/driver_diagnostic.py`: explicitly starts ONE test, displays firmware
  register readback, logs the manual meter reading with units and observations.
- Boot is stopped. Each run stops after 2 seconds, or after 400 ms without a host
  heartbeat. There is a 5-second cooldown. Invalid commands stop the outputs.
- Choices: 25% or 50% **drive duty**, 1 kHz or 20 kHz, drive/coast or drive/brake.
  No 100% drive, reverse tests, automatic sweeps, or unattended repeats.
- LEDC readback verifies peripheral settings, not the waveform at a driver input.
  No existing current/voltage feedback connects these driver outputs to the ESP32.
  The firmware cannot read a DRV8871 fault code or prove current limiting.
- Stops are software controlled; the battery switch is the physical cutoff.
  A 50% limit is not proof that a tiny motor tolerates the peak current of 7 V PWM.

## Setup and first run

1. Switch off and unplug battery. Remove **both propellers**, secure the motor
   bodies and check for loose wire strands. Keep the right output capacitor out
   for the baseline, matching the latest test. Leave the supply capacitors intact.
2. Connect boat ESP32 to USB. Confirm the external 5 V feed is isolated if the
   board's USB/external-power arrangement has not been verified. Keep grounds
   connected. Upload only the new diagnostic sketch to the **boat**.
3. First run with battery disconnected: confirm START followed by STOP time_limit.
   Disconnecting the host during a run must stop the signal. Confirm no motor
   command at boot. This verifies software operation before powered testing.
4. For powered tests, verify converter output near 7 V before reconnecting driver
   power. A DRV8871 requires at least 6.5 V; do not set its supply to 3.7 V.
5. Meter in **DC volts**, red lead in **V/ohms**, black in **COM**. Clip probes
   before starting. Apply battery power only after connections are settled.

Example from the repository folder, replacing BOAT_PORT with the identified port:

```sh
python3 tools/driver_diagnostic.py --port BOAT_PORT --side R --mode C --hz 1000 --percent 25 --load motor-no-prop --measure motor_output
```

Type RUN only when physically ready. Read **during** the 2-second window; readings
after STOP do not count. Enter the actual unit, e.g. `200 mV` or `0.2 V`, or leave
blank if missed. The script logs to `/tmp/airboat-driver-results.jsonl` by default;
use `--log` for a permanent location. Run each next trial manually. Stop immediately
if stalled, hot, or behaving unexpectedly. Never rewire while powered.

## Test sequence and meaning

Do one row at a time, and stop when evidence identifies the cause. Do not exhaust
the entire matrix blindly. Start at 25%; repeat at 50% only if the motor runs
normally without heating. A failure to start at low duty alone is not a fault.

| Test | Exact meter placement / change | What it distinguishes |
| --- | --- | --- |
| Right output baseline | Black right OUT2, red right OUT1; motor connected, no prop | Signed output reading under a reproducible command. Record spin too. |
| Supply under same command | Black right POWER−, red right POWER+ | Sustained supply loss; watch converter CC light. A steady DMM reading cannot exclude brief UVLO dips. |
| Supply wiring loss if needed | Measure between converter OUT+ and driver POWER+, then converter OUT− and driver POWER− during separate identical runs | Voltage lost in connectors or supply/return wiring. Repair the bad connection rather than increase supply voltage. |
| Control under load | Black right POWER−; red IN1, then IN2, separate runs | Coast: expected IN1 roughly 0.8 V at 25% or 1.65 V at 50%, IN2 near zero. Brake: IN1 roughly 3.3 V, IN2 roughly 2.48 V at 25% or 1.65 V at 50%. DMM averages only. |
| Ground reference if needed | Black driver POWER−; red ESP32 GND during run | A substantial voltage here indicates poor shared return; repair the ground wiring. |
| Frequency comparison | Same motor/driver/duty/mode; change only 1 kHz to 20 kHz | If repeatable improvement occurs, pulse timing interacts with driver/motor behavior. Does not alone identify a faulty component. |
| Mode comparison | Same motor/driver/frequency/duty; change only C to B | Separates coast/brake behavior. Output averages can differ by mode; compare physical spin and supply as well. |
| Driver swap | Power off. Move the SAME motor's two wires to other driver's OUT1/OUT2, preserving corresponding terminals; select L | If issue follows driver, inspect that board, wiring, ILIM and control connections. If both fail, common setup or same module-design issue remains possible. |
| Motor swap | Power off. SAME driver/settings, different known-working motor, no prop | If issue follows motor, inspect winding, wiring or mechanical load. If both fail, focus on common driver/power/control path. |
| Spare driver if available | Same known-working motor, wiring and command; substitute one purchased spare | Can isolate a damaged board without buying parts. Identical modules may share the same limiting configuration. |

If a connection is suspect, first power off and reterminate only that connection.
The motor connects only between OUT1 and OUT2, never one motor lead to the ground
bus when driven by the H-bridge. Motor wires carry current; their thickness does
not impose a 7 V limit. Excess resistance creates voltage drop under current.

## If the output still collapses

Review the measured ILIM resistor value against the actual board layout, with all
power off. Prior 97 kΩ / 17 kΩ readings were not sufficient to establish both
boards' actual thresholds. Do not short ILIM or replace its resistor blindly.
Nominal threshold is approximately 64,000 / resistance_in_ohms amperes; board
heating and protection impose additional limits. A threshold estimate is not a
measurement of motor current.

Next consider a supervised **series supply-current measurement** using the
U3401A, with an exact wiring walkthrough at that time. It measures driver supply
average current, not motor winding peak current. Do not put a meter in current
mode across the converter output or across motor output screws. Do not stall the
motor to estimate startup current. Converter CC evidence calls for checking the
actual limit and power capacity, not blindly turning CC up.

If static meter readings and swap tests cannot distinguish current chopping from
fast UVLO/protection cycling, an oscilloscope/current measurement or an appropriate
known load is needed. Software alone cannot resolve this ambiguity. Only after
finding the cause should normal joystick firmware be changed and restored.

Reference: [TI DRV8871 datasheet](https://www.ti.com/lit/ds/symlink/drv8871.pdf),
input truth table, current regulation, sleep timing, UVLO and protection sections.

## Build

```sh
"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" compile --fqbn 'esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,USBMode=hwcdc,CDCOnBoot=cdc' --build-path /private/tmp/airboat-driver-diagnostic-cache --output-dir /private/tmp/airboat-driver-diagnostic-build firmware/boat_driver_diagnostic
```

Building is not uploading. Existing boat/controller sketches remain unchanged.
