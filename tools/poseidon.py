"""Poseidon: read-only ground station for the Airboat controller and boat.

Finds both ESP32-S3 boards by USB serial number (their station MACs), reads the
existing diagnostic lines from each, and shows joystick, radio link, motor
estimate and turbidity panels side by side. It never writes to either port.

Motor numbers and the animated boat are estimates computed from joystick input, not measured
outputs. Turbidity appears when the controller runs
firmware/controller_link_telemetry and the boat runs
firmware/boat_l298_joystick_telemetry: the controller then prints
`TURB adc=<0-4095> mv=<GPIO4 millivolts>` lines relayed from the boat.
"""
import argparse
from collections import deque
import curses
import locale
import math
import re
import sys
import time

# Reuse the existing parser and motor mix unchanged (tools/ is on sys.path when
# this file is run as `python3 tools/poseidon.py`).
from controller_terminal import parse_line
import serial
from serial.tools import list_ports

CONTROLLER_SERIAL = 'E0:72:A1:D5:25:90'
BOAT_SERIAL = '44:1B:F6:FE:71:A8'
BAUD = 115200
STALE_S = 2.0
RESCAN_S = 2.0
DIVIDER_GAIN = 1.5  # (10k + 20k) / 20k: sensor volts = GPIO4 volts * 1.5
TURB_RE = re.compile(r'\bTURB\b.*?\badc=(\d+)(?:.*?\bmv=(\d+))?')

CYAN, GREEN, YELLOW, RED, BLUE = 1, 2, 3, 4, 5


class Feed:
    """One board's USB serial stream. Opened read-only; rescans after unplug."""

    def __init__(self, name, serial_number, fixed_port=None, enabled=True):
        self.name = name
        self.serial_number = serial_number
        self.fixed_port = fixed_port
        self.enabled = enabled
        self.conn = None
        self.port = None
        self.error = None
        self.buffer = bytearray()
        self.next_scan = 0.0
        self.opened_at = None
        self.last_line = None      # any line
        self.data = {}             # last parsed X/Y/BUTTON sample
        self.last = None           # time of last parsed sample
        self.arrivals = deque(maxlen=40)
        self.state = None          # boat: LINK OK / LINK LOST / WAITING
        self.state_at = None
        self.motors_disabled_at = None
        self.turb = None
        self.turb_at = None
        self.drive = None
        self.drive_at = None
        self.turb_hist = deque(maxlen=24)  # sensor volts, for the trend line

    def find_port(self):
        if self.fixed_port:
            return self.fixed_port
        for info in list_ports.comports():
            if (info.serial_number or '').upper() == self.serial_number:
                return info.device
        return None

    def poll(self, now, log):
        if not self.enabled:
            return []
        if self.conn is None:
            if now < self.next_scan:
                return []
            self.next_scan = now + RESCAN_S
            port = self.find_port()
            self.port = port
            if not port:
                self.error = None
                return []
            try:
                self.conn = serial.Serial(port, BAUD, timeout=0, exclusive=True)
            except (serial.SerialException, OSError) as exc:
                self.error = str(exc)
                return []
            self.error = None
            self.buffer.clear()
            self.opened_at = now
            log(self.name, f'opened {port} (read-only)')
        try:
            chunk = self.conn.read(min(max(self.conn.in_waiting, 1), 16384))
        except (serial.SerialException, OSError) as exc:
            self.close()
            self.error = str(exc)
            self.next_scan = now + RESCAN_S
            log(self.name, f'port lost: {exc}')
            return []
        self.buffer.extend(chunk)
        lines = []
        while b'\n' in self.buffer:
            raw, _, rest = self.buffer.partition(b'\n')
            self.buffer = bytearray(rest)
            lines.append(raw.decode(errors='replace').strip())
        if len(self.buffer) > 8192:
            self.buffer.clear()
            log(self.name, 'discarded oversized incomplete line')
        return lines

    def ingest(self, line, now):
        self.last_line = now
        if line.startswith('LINK OK'):
            self.state, self.state_at = 'LINK OK', now
        elif line.startswith('LINK LOST'):
            self.state, self.state_at = 'LINK LOST', now
        elif line.startswith('WAITING FOR CONTROLLER'):
            self.state, self.state_at = 'WAITING', now
        if 'MOTORS DISABLED' in line:
            self.motors_disabled_at = now
        drive = re.search(r'left=(\d+) right=(\d+)', line)
        if drive:
            armed = re.search(r'armed=([01])', line)
            if armed or line.startswith('L298 DRIVE'):
                self.drive = (int(drive[1]), int(drive[2]),
                              bool(int(armed[1])) if armed else '| ARMED |' in line)
                self.drive_at = now
        turb = TURB_RE.search(line) or re.search(r'TURBIDITY.*?raw=(\d+).*?adc_mV=([\d.]+)', line)
        if turb:
            self.turb = (int(turb[1]), round(float(turb[2])) if turb[2] else None)
            self.turb_at = now
            if self.turb[1] is not None:
                self.turb_hist.append(self.turb[1] / 1000 * DIVIDER_GAIN)
        parsed = parse_line(line)
        if parsed:
            self.data = parsed
            self.last = now
            self.arrivals.append(now)

    def fresh(self, when, now):
        return when is not None and now - when <= STALE_S

    def rate(self, now):
        a = self.arrivals
        if len(a) < 2 or a[-1] <= a[0] or not self.fresh(self.last, now):
            return 0.0
        return (len(a) - 1) / (a[-1] - a[0])

    def status(self, now, demo):
        if not self.enabled:
            return 'OFF', 0
        if not demo and self.conn is None:
            return ('ERROR', RED) if self.error else ('NOT FOUND', YELLOW)
        if self.last_line is None:
            return 'WAITING', YELLOW
        return ('LIVE', GREEN) if self.fresh(self.last_line, now) else ('STALE', YELLOW)

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except (serial.SerialException, OSError):
                pass
        self.conn = None


class Demo:
    """Simulated lines in the exact firmware formats. Never touches USB.
    Simulated TURB lines are shown under a SIMULATED label, never as real data."""

    def __init__(self, start):
        self.start = start
        self.next_ctl = 0.0
        self.next_boat = 0.0
        self.seq = 0
        self.ack = 0
        self.fail = 0

    def lines(self, now):
        t = now - self.start
        x = int(1915 + 1900 * math.sin(t * 0.7))
        y = int(1925 + 1900 * math.cos(t * 0.45))
        button = 'PRESSED' if int(t) % 9 == 0 else 'released'
        link_down = 20 <= t % 30 < 23
        ctl, boat = [], []
        while self.next_ctl <= t:
            self.seq += 5
            if link_down:
                self.fail += 5
            else:
                self.ack += 5
            ctl.append(f'TX seq={self.seq} X={x} Y={y} BUTTON={button} '
                       f'MAC_ACK={self.ack} FAIL={self.fail} pending=0')
            self.next_ctl += 0.25
        while self.next_boat <= t:
            if t < 1:
                boat.append('WAITING FOR CONTROLLER | MOTORS DISABLED')
            elif link_down:
                boat.append('LINK LOST (>500ms) | MOTORS DISABLED')
            else:
                boat.append(f'LINK OK | seq={self.seq} X={x} Y={y} BUTTON={button} | MOTORS DISABLED')
            if round(self.next_boat * 10) % 2 == 0:
                mv = int(1900 + 250 * math.sin(t * 0.2) + 40 * math.sin(t * 3.1))
                boat.append(f'TURB adc={mv * 4095 // 3100} mv={mv}')
            self.next_boat += 0.1
        return ctl, boat


def forward_only_motors(x, y, center_x=1915, center_y=1925, deadzone=0.05):
    """Proposed mix for a boat with NO reverse: each fan is 0..1.
    Pulling the stick back gives zero forward thrust; left/right still steer by
    running one fan harder than the other. Estimate only, not measured output."""
    def axis(value, center):
        value = max(0, min(4095, value))
        normalized = (value - center) / (4095 - center if value >= center else center)
        if abs(normalized) <= deadzone:
            return 0.0
        return math.copysign((abs(normalized) - deadzone) / (1 - deadzone), normalized)
    turn = axis(x, center_x)
    forward = max(0.0, -axis(y, center_y))
    return min(1.0, max(0.0, forward + turn)), min(1.0, max(0.0, forward - turn))


def turbidity_feed(ctl, boat, now):
    """Whichever board is currently reporting TURB lines: the boat over its own
    USB, or the controller relaying what the boat sent over the radio."""
    for feed, via in ((boat, 'boat USB'), (ctl, 'radio via controller')):
        if feed.fresh(feed.turb_at, now):
            return feed, via
    return None, None


def motor_bar(value, half=10):
    filled = round(min(1.0, abs(value)) * half)
    left = ['.'] * half
    right = ['.'] * half
    for i in range(filled):
        if value < 0:
            left[half - 1 - i] = '#'
        else:
            right[i] = '#'
    return '[' + ''.join(left) + '|' + ''.join(right) + ']'


# Top-down airboat, bow up. L / R mark the two fan props at the stern.
BOAT_SPRITES = {
    0: ['    /\\    ',
        '   /  \\   ',
        '   |  |   ',
        '   |  |   ',
        '   |__|   ',
        '  (L)(R)  '],
    1: ['      __  ',
        '     /  / ',
        '    /  /  ',
        '   /  /   ',
        '  /__/    ',
        ' (L)(R)   '],
    -1: ['  __      ',
         ' \\  \\     ',
         '  \\  \\    ',
         '   \\  \\   ',
         '    \\__\\  ',
         '   (L)(R) '],
}
SPINNER = '|/-\\'
SPARK = ' .:-=+*#'


def sparkline(values, width):
    values = list(values)[-width:]
    if not values:
        return ''
    lo, hi = min(values), max(values)
    if hi - lo < 0.005:  # steady reading: draw a flat line, not blanks
        return '-' * len(values)
    span = hi - lo
    return ''.join(SPARK[min(len(SPARK) - 1, int((v - lo) / span * (len(SPARK) - 1) + 0.5))] for v in values)


class BoatAnimation:
    """Animated top-down boat driven by the proposed motor mix. Purely visual:
    position follows the joystick, props spin with each side's estimated demand,
    and the water scrolls with forward demand. It is not measured motion."""

    def __init__(self):
        self.scroll = 0.0
        self.prop = [0.0, 0.0]
        self.last = None

    def draw(self, put, top, left, width, height, lm, rm, live, pressed, now):
        dt = 0.0 if self.last is None else min(0.2, now - self.last)
        self.last = now
        forward = (lm + rm) / 2
        turn = (lm - rm) / 2
        if live:
            self.scroll += forward * 6 * dt
            self.prop[0] += lm * 25 * dt
            self.prop[1] += rm * 25 * dt
        # Water: diagonal ripples that flow downward when moving forward.
        s = int(self.scroll)
        for r in range(height):
            row = ''.join('~' if (c * 3 + (r - s) * 5) % 13 == 0 else ' ' for c in range(width))
            put(top + r, left, row, BLUE)
        sprite = BOAT_SPRITES[1 if turn > 0.2 else -1 if turn < -0.2 else 0]
        sw = len(sprite[0])
        bx = left + (width - sw) // 2 + round(turn * (width - sw) / 2)
        by = top + 1 + (-1 if forward > 0.3 else 1 if forward < -0.3 else 0)
        hull_color = (YELLOW if pressed else GREEN) if live else 0
        props = {}
        for i, line in enumerate(sprite):
            y = by + i
            if not top <= y < top + height:
                continue
            body = line.rstrip()
            first = len(line) - len(line.lstrip())
            for j in range(first, len(body)):
                ch = body[j]
                if ch in 'LR':
                    props[ch] = (y, bx + j)
                    side = 0 if ch == 'L' else 1
                    ch = SPINNER[int(self.prop[side]) % 4] if live else 'o'
                    put(y, bx + j, ch, CYAN, True)
                else:
                    put(y, bx + j, ch, hull_color, True)
        # Prop wash behind each fan, length follows that side's demand.
        for ch, v in (('L', lm), ('R', rm)):
            if ch in props and live:
                y, x = props[ch]
                for k in range(1, round(abs(v) * 3) + 1):
                    if y + k < top + height:
                        put(y + k, x, ':' if v > 0 else '.', CYAN)
        if pressed and live:
            put(top, left + width - 7, 'HONK!', YELLOW, True)


def dashboard(screen, ctl, boat, args):
    curses.curs_set(0)
    screen.nodelay(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for index, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW,
                                       curses.COLOR_RED, curses.COLOR_BLUE), 1):
            curses.init_pair(index, color, -1)
    logs = deque(maxlen=6)
    start = time.monotonic()
    demo = Demo(start) if args.demo else None
    animation = BoatAnimation()
    next_frame = 0.0

    def log(source, text):
        logs.append((source, text))

    def put(y, x, text, color=0, bold=False):
        h, w = screen.getmaxyx()
        if 0 <= y < h - 1 and 0 <= x < w - 1:
            attr = curses.color_pair(color) if curses.has_colors() else 0
            try:
                screen.addnstr(y, x, text, w - x - 1, attr | (curses.A_BOLD if bold else 0))
            except curses.error:
                pass

    def card(y, x, width, height, title):
        put(y, x, '+' + '-' * (width - 2) + '+', CYAN)
        put(y + 1, x, '| ' + title[:width - 4].ljust(width - 4) + ' |', CYAN, True)
        put(y + 2, x, '+' + '-' * (width - 2) + '+', CYAN)
        for row in range(y + 3, y + height - 1):
            put(row, x, '|', CYAN)
            put(row, x + width - 1, '|', CYAN)
        put(y + height - 1, x, '+' + '-' * (width - 2) + '+', CYAN)

    if args.demo:
        ctl.port = boat.port = 'SIMULATED'

    while True:
        now = time.monotonic()
        if demo:
            ctl_lines, boat_lines = demo.lines(now)
        else:
            ctl_lines, boat_lines = ctl.poll(now, log), boat.poll(now, log)
        for feed, lines in ((ctl, ctl_lines), (boat, boat_lines)):
            for line in lines:
                if not line:
                    continue
                previous_state = feed.state
                feed.ingest(line, now)
                # Keep the log readable: the boat repeats its status at 10 Hz and
                # TURB at 5 Hz (shown in its panel), so log only status changes.
                if line.startswith('TURB'):
                    continue
                if feed is boat and line.startswith(('LINK OK', 'LINK LOST', 'WAITING')) \
                        and feed.state == previous_state:
                    continue
                log(feed.name, line)

        if now < next_frame:
            time.sleep(0.002)
            continue
        next_frame = now + 1 / 30

        screen.erase()
        h, w = screen.getmaxyx()
        L, R, CW = 1, 51, 48

        # Header
        put(0, 2, '\\ | /', CYAN, True)
        put(1, 2, ' \\|/ ', CYAN, True)
        put(2, 2, '  |  ', CYAN, True)
        put(0, 10, 'P O S E I D O N', CYAN, True)
        put(1, 10, 'Airboat ground station  /  read-only  /  115200 baud', 0)
        if args.demo:
            put(2, 10, 'SIMULATION MODE - NO HARDWARE DATA', YELLOW, True)
        else:
            put(2, 10, f'CTL {ctl.port or "--"}    BOAT {boat.port or "--"}', 0)
        x = 2
        for feed in (ctl, boat):
            text, color = feed.status(now, args.demo)
            age = f'{now - feed.last_line:.1f}s' if feed.last_line else '--'
            chunk = f'{feed.name} [{text}] {feed.rate(now):4.1f} Hz  age {age}'
            put(4, x, chunk, color, True)
            x += len(chunk) + 4
        put(4, x, 'Q TO QUIT', 0)

        # Joystick (controller TX if fresh, else what the boat received)
        card(6, L, CW, 15, 'Joystick')
        if ctl.fresh(ctl.last, now):
            src, js, jcolor = 'controller TX', ctl.data, GREEN
        elif boat.state == 'LINK OK' and boat.fresh(boat.last, now):
            src, js, jcolor = 'boat RX', boat.data, GREEN
        else:
            src, js, jcolor = 'no fresh input', (ctl.data or boat.data), YELLOW
        put(9, L + 3, f'X {js.get("x", "--"):>5}   Y {js.get("y", "--"):>5}   ', CYAN, True)
        put(9, L + 27, f'BUTTON {js.get("button", "--")}',
            YELLOW if js.get('button') == 'PRESSED' else jcolor, True)
        put(10, L + 3, f'source: {src}', jcolor)
        gw, gh = 29, 7
        grid = [[' '] * gw for _ in range(gh)]
        for row in range(gh):
            grid[row][gw // 2] = ':'
        grid[gh // 2] = list('.' * gw)
        grid[gh // 2][gw // 2] = '+'
        if js:
            gx = round(min(4095, js['x']) / 4095 * (gw - 1))
            gy = round(min(4095, js['y']) / 4095 * (gh - 1))
            grid[gy][gx] = '@'
        put(11, L + 3, '          FORWARD', CYAN)
        for i, row in enumerate(grid):
            put(12 + i, L + 3, '[' + ''.join(row) + ']', jcolor)
        put(19, L + 3, '          BACKWARD   raw ADC, uncalibrated', CYAN)

        # Radio link
        card(21, L, CW, 8, 'Radio link')
        if boat.state and boat.fresh(boat.state_at, now):
            st, scolor = boat.state, {'LINK OK': GREEN, 'LINK LOST': RED}.get(boat.state, YELLOW)
        else:
            st, scolor = ('no boat feed' if not boat.last_line else 'boat feed stale'), YELLOW
        put(24, L + 3, f'Boat      {st}', scolor, True)
        cseq, bseq = ctl.data.get('seq'), boat.data.get('seq')
        lag = f'(lag {cseq - bseq})' if cseq is not None and bseq is not None else ''
        put(25, L + 3, f'Seq       ctl {cseq if cseq is not None else "--"}   boat {bseq if bseq is not None else "--"}  {lag}')
        ack, fail = ctl.data.get('MAC_ACK'), ctl.data.get('FAIL')
        ratio = f'{ack / (ack + fail):.1%} acked' if ack is not None and fail is not None and ack + fail else ''
        put(26, L + 3, f'MAC_ACK   {ack if ack is not None else "--"}   FAIL {fail if fail is not None else "--"}   {ratio}')
        put(27, L + 3, 'ACK: radio delivery   LINK OK: boat receipt', 0)

        # Animated boat + motor estimate
        if boat.state == 'LINK OK' and boat.fresh(boat.last, now):
            msrc, mdata = 'boat RX', boat.data
        elif ctl.fresh(ctl.last, now):
            msrc, mdata = 'controller TX', ctl.data
        else:
            msrc, mdata = None, None
        card(6, R, CW, 15, f'Poseidon  (motor estimate from {msrc or "--"})')
        if mdata:
            lm, rm = forward_only_motors(mdata['x'], mdata['y'], args.center_x, args.center_y, args.deadzone)
        else:
            lm = rm = 0.0
        animation.draw(put, 9, R + 2, CW - 4, 8, lm, rm, bool(mdata),
                       bool(mdata) and mdata.get('button') == 'PRESSED', now)
        if mdata:
            for row, label, v in ((17, 'L', lm), (18, 'R', rm)):
                put(row, R + 3, f'{label} {motor_bar(v)} {v:+5.0%} ~{v * args.motor_voltage:+5.2f}V est',
                    GREEN, True)
        else:
            put(17, R + 3, 'L --   R --   no fresh joystick input', YELLOW)
        if boat.fresh(boat.motors_disabled_at, now):
            put(19, R + 3, 'Boat says: MOTORS DISABLED', YELLOW, True)
        else:
            put(19, R + 3, 'Boat output: unknown', YELLOW)
        put(19, R + 31, f'{args.motor_voltage:g}V assumed', 0)

        # Turbidity
        tlabel = '  SIMULATED' if args.demo else ''
        card(21, R, CW, 8, f'Turbidity  (SEN0189 / GPIO4){tlabel}')
        tfeed, tvia = turbidity_feed(ctl, boat, now)
        if tfeed:
            adc, mv = tfeed.turb
            if mv is not None:
                put(24, R + 3, f'ADC {adc:>4}  GPIO4 {mv / 1000:.3f}V  sensor ~{mv / 1000 * DIVIDER_GAIN:.2f}V',
                    YELLOW if args.demo else GREEN, True)
            else:
                put(24, R + 3, f'ADC {adc:>4}  (no mv field)', GREEN, True)
            hist = tfeed.turb_hist
            if hist:
                put(25, R + 3, f'trend [{sparkline(hist, 24):<24}] {min(hist):.2f}-{max(hist):.2f}V', CYAN)
            put(26, R + 3, '--  NTU  (needs calibration)', YELLOW, True)
            put(27, R + 3, f'via {tvia} / murkier = lower V', 0)
        elif boat.last_line or ctl.last_line:
            put(24, R + 3, '--  NTU   no TURB lines yet', YELLOW, True)
            put(25, R + 3, 'Boards are running sketches without', 0)
            put(26, R + 3, 'turbidity (needs the telemetry', 0)
            put(27, R + 3, 'sketches).', 0)
        else:
            put(24, R + 3, '--  NTU   no boat feed', YELLOW, True)
            put(25, R + 3, 'Needs the telemetry sketches on both', 0)
            put(26, R + 3, 'boards, and the boat powered.', 0)

        # Log
        put(29, 1, ' Serial log ' + '-' * 86, CYAN, True)
        for i, (source, text) in enumerate(logs):
            put(30 + i, 2, f'{source:<4}', BLUE if source == 'BOAT' else CYAN, True)
            put(30 + i, 7, text)
        put(36, 2, 'Never sends serial commands. Keep the motor supply disconnected.', YELLOW, True)
        if h < 38 or w < 100:
            put(h - 2, 1, f' Terminal is {w}x{h}; enlarge to 100x38 for the full view.', YELLOW, True)
        screen.refresh()
        if screen.getch() in (3, ord('q'), ord('Q')):
            break
        time.sleep(0.002)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--demo', action='store_true', help='Simulated data, clearly labeled; no USB access')
    parser.add_argument('--list-ports', action='store_true', help='List ports and mark the controller and boat')
    parser.add_argument('--controller-port', help=f'Override auto-detect (USB serial {CONTROLLER_SERIAL})')
    parser.add_argument('--boat-port', help=f'Override auto-detect (USB serial {BOAT_SERIAL})')
    parser.add_argument('--no-controller', action='store_true', help='Do not open the controller port')
    parser.add_argument('--no-boat', action='store_true', help='Do not open the boat port')
    parser.add_argument('--motor-voltage', type=float, default=7.0, help='Assumed motor rail in volts; NOT measured (default 7)')
    parser.add_argument('--center-x', type=int, default=1915)
    parser.add_argument('--center-y', type=int, default=1925)
    parser.add_argument('--deadzone', type=float, default=0.05)
    args = parser.parse_args()
    if not math.isfinite(args.motor_voltage) or args.motor_voltage <= 0:
        parser.error('--motor-voltage must be finite and positive')
    if not (0 < args.center_x < 4095 and 0 < args.center_y < 4095):
        parser.error('Axis centers must be between 1 and 4094')
    if not 0 <= args.deadzone < 1:
        parser.error('--deadzone must be between 0 (inclusive) and 1 (exclusive)')

    if args.list_ports:
        roles = {CONTROLLER_SERIAL: 'CONTROLLER', BOAT_SERIAL: 'BOAT'}
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        for p in ports:
            role = roles.get((p.serial_number or '').upper(), '')
            print(f'{role:<11}{p.device}  {p.description}  serial={p.serial_number or "unknown"}')
        if not any((p.serial_number or '').upper() in roles for p in ports):
            print('Neither board found. Check USB data cables and use the native USB connector.')
        return 0

    if not sys.stdout.isatty():
        print('Run Poseidon in an interactive terminal (100x38 or larger).', file=sys.stderr)
        return 1

    locale.setlocale(locale.LC_ALL, '')
    ctl = Feed('CTL', CONTROLLER_SERIAL, args.controller_port, not args.no_controller)
    boat = Feed('BOAT', BOAT_SERIAL, args.boat_port, not args.no_boat)
    try:
        curses.wrapper(dashboard, ctl, boat, args)
    except KeyboardInterrupt:
        pass
    except curses.error as exc:
        print(f'Dashboard error: {exc}', file=sys.stderr)
        return 1
    finally:
        ctl.close()
        boat.close()
    print('Poseidon closed; serial ports released.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
