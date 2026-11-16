"""One supervised, bounded driver test; logs serial output and manual measurements.

Requires boat_driver_diagnostic firmware and pyserial. Never uploads firmware.
"""
import argparse
import datetime
import json
from pathlib import Path
import time


def voltage(text):
    """Require explicit units so 0.2 V cannot silently become 0.2 mV."""
    import re
    import math
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mV|V)\s*", text)
    if not match:
        raise ValueError("Use explicit units, for example 0.2 V or 200 mV")
    value = float(match[1]) / (1000 if match[2] == "mV" else 1)
    if not math.isfinite(value):
        raise ValueError("Reading must be finite")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Explicit BOAT USB port")
    parser.add_argument("--side", choices=["R", "L"], default="R")
    parser.add_argument("--mode", choices=["C", "B"], default="C", help="C=coast; B=brake")
    parser.add_argument("--hz", choices=[1000, 20000], type=int, default=1000)
    parser.add_argument("--percent", choices=[25, 50], type=int, default=25)
    parser.add_argument("--load", choices=["motor-no-prop", "disconnected"], required=True)
    parser.add_argument("--measure", choices=["driver_supply", "motor_output", "IN1", "IN2", "ground_drop"], required=True)
    parser.add_argument("--log", type=Path, default=Path("/tmp/airboat-driver-results.jsonl"))
    args = parser.parse_args()
    import serial

    record = {**vars(args), "log": str(args.log), "time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "serial": []}
    def capture(connection):
        line = connection.readline().decode(errors="replace").strip()
        if line:
            print(line)
            record["serial"].append(line)
        return line

    try:
        with serial.Serial(args.port, 115200, timeout=.03, write_timeout=.2, exclusive=True) as connection:
            connection.write(b"STOP\nINFO\n")
            deadline = time.monotonic() + 5
            identified = False
            while time.monotonic() < deadline:
                if capture(connection).startswith("AIRBOAT_DIAG_V1"):
                    identified = True
                    break
                connection.write(b"INFO\n")
            if not identified:
                raise RuntimeError("Diagnostic firmware not identified. No RUN sent.")
            print(f"ONE test: {args.side}, {args.percent}% drive, {args.hz} Hz, mode {args.mode}, load {args.load}.")
            print("Remove BOTH propellers; secure motor. Driver supply must be verified near 7 V.")
            print("Meter: DC volts, red lead in V/ohms, black in COM. Set probes BEFORE starting.")
            print("This is a 2-second test, NOT a guarantee against motor damage. Battery switch is the physical stop.")
            print("Confirm the wiring/load matches the chosen test. No wire changes while powered.")
            if input("Type RUN to start, anything else cancels: ").strip() != "RUN":
                record["result"] = "cancelled"
                return
            connection.reset_input_buffer()
            try:
                connection.write(f"PING\nRUN {args.side} {args.mode} {args.hz} {args.percent}\n".encode())
                deadline = time.monotonic() + 3.5
                next_ping = 0
                started = False
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_ping:
                        connection.write(b"PING\n")
                        next_ping = time.monotonic() + .1
                    line = capture(connection)
                    started |= line.startswith("START ")
                    if line.startswith(("REJECT ", "STOP ")):
                        record["result"] = line
                        break
                else:
                    raise RuntimeError("No automatic STOP received; switch off battery and inspect log.")
            finally:
                connection.write(b"STOP\n")
            if started and record.get("result") == "STOP time_limit":
                while True:
                    reading = input("Reading DURING the run (e.g. 200 mV), or Enter if missed: ")
                    if not reading.strip():
                        record["reading_volts"] = None
                        break
                    try:
                        record["reading_volts"] = voltage(reading)
                        record["reading_original"] = reading
                        break
                    except ValueError as exc:
                        print(exc)
                record["observation"] = input("Observed spin / converter CC light / other notes: ")
            print("Test ended. Switch off and unplug battery before changing connections.")
    except (KeyboardInterrupt, Exception) as exc:
        record["error"] = str(exc) or "Interrupted"
        print("Test interrupted/error. Switch off battery.", record["error"])
        return 1
    finally:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a") as log:
            log.write(json.dumps(record) + "\n")
        print(f"Results saved: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
