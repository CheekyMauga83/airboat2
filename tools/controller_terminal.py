"""Read-only Airboat serial dashboard; no firmware upload or serial commands."""
import argparse
from collections import deque
import curses
import math
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit('Missing pyserial. Run: python3 -m pip install pyserial')


def parse_line(line):
    match = re.search(r'X=\s*(\d+)\s+Y=\s*(\d+)\s+BUTTON=(PRESSED|released)', line)
    if not match:
        return None
    data = dict(x=int(match[1]), y=int(match[2]), button=match[3])
    for key in ('seq', 'MAC_ACK', 'FAIL', 'pending'):
        field = re.search(rf'\b{key}=(\d+)', line)
        if field:
            data[key] = int(field[1])
    return data


def estimate_motors(x, y, center_x=1915, center_y=1925, deadzone=0.05):
    """Proposed differential mix only; signed duty demand, not measured speed."""
    def axis(value, center):
        value = max(0, min(4095, value))
        normalized = (value-center) / (4095-center if value >= center else center)
        if abs(normalized) <= deadzone:
            return 0.0
        return math.copysign((abs(normalized)-deadzone)/(1-deadzone), normalized)
    turn = axis(x, center_x)
    forward = -axis(y, center_y)
    left, right = forward + turn, forward - turn
    scale = max(1, abs(left), abs(right))
    return left / scale, right / scale


def dashboard(screen, connection, port, demo=False, voltage=7.0, center_x=1915, center_y=1925, deadzone=0.05):
    curses.curs_set(0)
    screen.nodelay(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for index, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN,
                                       curses.COLOR_YELLOW, curses.COLOR_RED), 1):
            curses.init_pair(index, color, -1)
    data = {}
    arrivals = deque(maxlen=40)
    logs = deque(maxlen=6)
    buffer = bytearray()
    start = time.monotonic()
    last = None
    error = None
    next_demo = 0
    next_frame = 0

    def put(y, text, color=0, bold=False, x=0):
        h, w = screen.getmaxyx()
        if 0 <= y < h - 1 and 0 <= x < w - 1:
            attr = curses.color_pair(color) if curses.has_colors() else 0
            try:
                screen.addnstr(y, x, text, w - x - 1, attr | (curses.A_BOLD if bold else 0))
            except curses.error:
                pass

    def card(y, x, width, height, title):
        put(y, '+' + '-' * (width - 2) + '+', 1, x=x)
        put(y + 1, '| ' + title[:width-4].ljust(width-4) + ' |', 1, True, x)
        put(y + 2, '+' + '-' * (width - 2) + '+', 1, x=x)
        for row in range(y + 3, y + height - 1):
            put(row, '|', 1, x=x)
            put(row, '|', 1, x=x+width-1)
        put(y + height - 1, '+' + '-' * (width - 2) + '+', 1, x=x)

    while True:
        now = time.monotonic()
        lines = []
        if demo and now >= next_demo:
            seq = int((now - start) * 4)
            lines = [f'TX seq={seq} X={int(2047+1900*math.sin(now))} Y={int(2047+1900*math.cos(now))} BUTTON={"PRESSED" if seq % 12 < 3 else "released"} MAC_ACK={seq} FAIL=0 pending=0']
            next_demo = now + .25
        elif connection and not error:
            try:
                chunk = connection.read(min(max(connection.in_waiting, 1), 16384))
                buffer.extend(chunk)
                while b'\n' in buffer:
                    raw, _, buffer = buffer.partition(b'\n')
                    lines.append(raw.decode(errors='replace').strip())
                if len(buffer) > 8192:
                    buffer.clear()
                    logs.append('Discarded oversized incomplete serial line')
            except (serial.SerialException, OSError) as exc:
                error = str(exc)
        for line in lines:
            if line:
                logs.append(line)
            parsed = parse_line(line)
            if parsed:
                data = parsed
                last = now
                arrivals.append(now)
        age = now - last if last is not None else None
        stale = age is None or age > 2
        status = 'DISCONNECTED' if error else ('WAITING FOR DATA' if age is None else ('STALE' if stale else 'LIVE'))
        rate = (len(arrivals)-1)/(arrivals[-1]-arrivals[0]) if len(arrivals)>1 and arrivals[-1]>arrivals[0] and not stale else 0
        # Drain USB frequently; cap terminal drawing independently at 60 FPS.
        if now < next_frame:
            time.sleep(.002)
            continue
        next_frame = now + 1 / 60
        screen.erase()
        h, w = screen.getmaxyx()
        wide = w >= 96
        panel_width = min(46, max(30, w - 3))
        right = panel_width + 3 if wide else 1
        sensor_top = 6 if wide else 24
        feed_top = 25 if wide else 43
        age_text = f'{age:.2f}s' if age is not None else '--'
        signal_color = 4 if error else (3 if stale else 2)
        put(0, ' Airboat', 1, True)
        put(1, ' Controller feedback', 1)
        put(2, ' SIMULATION MODE - NO HARDWARE DATA' if demo else f' {port}  /  115200 BAUD', 3 if demo else 0)
        put(4, f' [{status}]   {rate:4.1f} Hz INPUT   {age_text} AGE   /   CTRL+C TO EXIT', signal_color, True)

        card(6, 1, panel_width, 18, 'Joystick')
        put(9, f'X  {data.get("x", "--"):>5}    Y  {data.get("y", "--"):>5}', 1, True, 4)
        put(10, f'BUTTON  {data.get("button", "--")}', 3 if data.get('button') == 'PRESSED' else signal_color, True, 4)
        grid_width, grid_height = min(29, panel_width-8), 7
        grid = [[' '] * grid_width for _ in range(grid_height)]
        for row in range(grid_height):
            grid[row][grid_width//2] = ':'
        grid[grid_height//2] = list('.' * grid_width)
        grid[grid_height//2][grid_width//2] = '+'
        if data:
            gx = round(min(4095, data['x']) / 4095 * (grid_width-1))
            gy = round(min(4095, data['y']) / 4095 * (grid_height-1))
            grid[gy][gx] = '@'
        put(12, '       FORWARD / Y=0', 1, x=4)
        for i, row in enumerate(grid):
            put(13+i, '[' + ''.join(row) + ']', signal_color, x=4)
        put(20, '       BACKWARD / Y=4095', 1, x=4)
        put(21, 'RAW ADC / UNCALIBRATED', 0, x=4)
        put(22, 'L: X=0    R: X=4095', 0, x=4)

        card(sensor_top, right, panel_width, 10, 'Turbidity')
        put(sensor_top+3, 'TURBIDITY', 1, True, right+3)
        put(sensor_top+4, '--  NTU', 0, True, right+3)
        put(sensor_top+5, '[ . . . . . . . . . . ]', 0, x=right+3)
        put(sensor_top+6, 'No sensor data', 3, True, right+3)
        put(sensor_top+7, 'Placeholder / no sensor feed', 0, x=right+3)
        put(sensor_top+8, 'SEN0189 / calibration pending', 0, x=right+3)

        card(sensor_top+11, right, panel_width, 7, 'Motor estimate / not applied')
        if data and not stale and not error:
            left, right_motor = estimate_motors(data['x'], data['y'], center_x, center_y, deadzone)
            put(sensor_top+14, f'L {left:+.0%} ~{left*voltage:+.2f}V', 1, x=right+3)
            put(sensor_top+15, f'R {right_motor:+.0%} ~{right_motor*voltage:+.2f}V', 1, x=right+3)
        else:
            put(sensor_top+14, 'L --    R -- / no fresh input', 3, x=right+3)
            put(sensor_top+15, 'Estimate unavailable', 0, x=right+3)
        put(sensor_top+16, f'Rail assumed {voltage:g}V / RPM unknown', 3, x=right+3)

        put(feed_top, ' Serial log ' + '-' * max(0, min(w-22, 65)), 1, True)
        if error:
            put(feed_top+1, ' CONNECTION ERROR: '+error, 4, True)
            put(feed_top+2, ' Check cable/port; close other serial monitors; restart.', 3)
        else:
            for i, line in enumerate(logs):
                put(feed_top+1+i, ' '+line)
        put(feed_top+8, ' MAC_ACK: radio delivery / Boat LINK OK: application receipt', 0)
        put(feed_top+9, ' Keep motor supply disconnected.', 3, True)
        if h < feed_top+12:
            put(h-2, ' Enlarge terminal: 96 x 37 for full view / narrow mode needs 55 rows.', 3)
        screen.refresh()
        key = screen.getch()
        if key in (3, ord('q'), ord('Q')):
            break
        time.sleep(.002)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='/dev/cu.usbmodem101')
    parser.add_argument('--list-ports', action='store_true')
    parser.add_argument('--demo', action='store_true', help='Clearly labeled simulated preview; no USB access')
    parser.add_argument('--motor-voltage', type=float, default=7.0, help='Assumed motor rail in volts; NOT a measurement (default: 7)')
    parser.add_argument('--center-x', type=int, default=1915)
    parser.add_argument('--center-y', type=int, default=1925)
    parser.add_argument('--deadzone', type=float, default=0.05, help='Normalized assumed dead zone (default: .05)')
    args = parser.parse_args()
    if not math.isfinite(args.motor_voltage) or args.motor_voltage <= 0:
        parser.error('--motor-voltage must be finite and positive')
    if not (0 < args.center_x < 4095 and 0 < args.center_y < 4095):
        parser.error('Axis centers must be between 1 and 4094')
    if not 0 <= args.deadzone < 1:
        parser.error('--deadzone must be between 0 (inclusive) and 1 (exclusive)')
    if args.list_ports:
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        for port in ports:
            print(f'{port.device}  {port.description}  serial={port.serial_number or "unknown"}')
        if not ports: print('No serial ports found. Check USB cables and board power.')
        return 0
    if not sys.stdout.isatty():
        print('Run this dashboard in an interactive terminal (VS Code Terminal > New Terminal).', file=sys.stderr)
        return 1
    connection = None
    try:
        if not args.demo:
            connection = serial.Serial(args.port, 115200, timeout=0, exclusive=True)
        curses.wrapper(dashboard, connection, args.port, args.demo, args.motor_voltage, args.center_x, args.center_y, args.deadzone)
    except KeyboardInterrupt:
        pass
    except (serial.SerialException, OSError, curses.error) as exc:
        print(f'Connection/dashboard error: {exc}', file=sys.stderr)
        print('Close other monitors on this port. Verify ports with --list-ports.\nIf USB is blocked here, run the same command in VS Code terminal 2.', file=sys.stderr)
        return 1
    finally:
        if connection:
            connection.close()
    print('Controller monitor closed; serial port released.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
