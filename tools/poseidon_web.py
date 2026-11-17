"""Poseidon web: the same read-only ground station, in a browser.

Runs a small local server (loopback only) that reads both boards' existing
serial diagnostics and streams them to tools/poseidon_web.html. It never writes
to either serial port and has no control endpoints: the page can only watch.

    python3 tools/poseidon_web.py --demo     # simulated data, no USB
    python3 tools/poseidon_web.py            # live boards, found by USB serial

Then open http://127.0.0.1:8765
"""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time

from poseidon import (BOAT_SERIAL, CONTROLLER_SERIAL, DIVIDER_GAIN, Demo, Feed,
                      forward_only_motors, turbidity_feed)

PAGE = Path(__file__).with_name('poseidon_web.html')


class Bridge:
    """Owns the serial feeds and keeps the latest JSON snapshot for the page."""

    def __init__(self, args):
        self.args = args
        self.ctl = Feed('CTL', CONTROLLER_SERIAL, args.controller_port, not args.no_controller)
        self.boat = Feed('BOAT', BOAT_SERIAL, args.boat_port, not args.no_boat)
        self.demo = Demo(time.monotonic()) if args.demo else None
        if args.demo:
            self.ctl.port = self.boat.port = 'SIMULATED'
        self.logs = deque(maxlen=14)
        self.log_id = 0
        self.turb_count = {'CTL': 0, 'BOAT': 0}
        self.snapshot = b'{}'
        self.stop = threading.Event()

    def log(self, source, text):
        self.log_id += 1
        self.logs.append({'id': self.log_id, 'src': source, 'text': text})

    def run(self):
        next_snapshot = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            if self.demo:
                ctl_lines, boat_lines = self.demo.lines(now)
            else:
                ctl_lines = self.ctl.poll(now, self.log)
                boat_lines = self.boat.poll(now, self.log)
            for feed, lines in ((self.ctl, ctl_lines), (self.boat, boat_lines)):
                for line in lines:
                    if not line:
                        continue
                    previous_state = feed.state
                    feed.ingest(line, now)
                    if line.startswith('TURB'):
                        self.turb_count[feed.name] += 1
                        continue
                    if feed is self.boat and line.startswith(('LINK OK', 'LINK LOST', 'WAITING')) \
                            and feed.state == previous_state:
                        continue
                    self.log(feed.name, line)
            if now >= next_snapshot:
                next_snapshot = now + 0.05
                self.snapshot = json.dumps(self.build(now)).encode()
            time.sleep(0.003)
        self.ctl.close()
        self.boat.close()

    def feed_info(self, feed, now):
        text, _ = feed.status(now, bool(self.demo))
        return {'status': text, 'port': feed.port, 'error': feed.error,
                'rate': round(feed.rate(now), 1),
                'age': round(now - feed.last_line, 2) if feed.last_line else None}

    def build(self, now):
        ctl, boat, args = self.ctl, self.boat, self.args
        boat_ok = boat.state == 'LINK OK' and boat.fresh(boat.last, now)
        if ctl.fresh(ctl.last, now):
            js_src, js = 'controller TX', ctl.data
        elif boat_ok:
            js_src, js = 'boat RX', boat.data
        else:
            js_src, js = None, None
        drive_feed = next((f for f in (ctl, boat) if f.fresh(f.drive_at, now)), None)
        motors = None
        armed = None
        if drive_feed:
            left, right, armed = drive_feed.drive
            motors = {'left': left / 256, 'right': right / 256,
                      'source': 'boat-reported PWM duty'}
        turb = None
        tfeed, tvia = turbidity_feed(ctl, boat, now)
        if tfeed:
            adc, mv = tfeed.turb
            turb = {'adc': adc, 'mv': mv, 'n': self.turb_count[tfeed.name], 'via': tvia,
                    'sensorV': round(mv / 1000 * DIVIDER_GAIN, 3) if mv is not None else None}
        link = boat.state if boat.state and boat.fresh(boat.state_at, now) else None
        if link is None and ctl.fresh(ctl.turb_at, now):
            link = 'TELEMETRY LIVE'
        return {
            'demo': bool(self.demo),
            'ctl': self.feed_info(ctl, now),
            'boat': self.feed_info(boat, now),
            'joystick': dict(js, source=js_src) if js else None,
            'centers': {'x': args.center_x, 'y': args.center_y},
            'motors': motors,
            'railV': args.motor_voltage,
            'armed': armed,
            'motorsDisabled': armed is False or boat.fresh(boat.motors_disabled_at, now),
            'link': {'state': link, 'ctlSeq': ctl.data.get('seq'), 'boatSeq': boat.data.get('seq'),
                     'ack': ctl.data.get('MAC_ACK'), 'fail': ctl.data.get('FAIL')},
            'turb': turb,
            'boatHasFeed': boat.last_line is not None,
            'log': list(self.logs),
        }


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            elif self.path == '/events':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    while not bridge.stop.is_set():
                        self.wfile.write(b'data: ' + bridge.snapshot + b'\n\n')
                        self.wfile.flush()
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            else:
                self.send_error(404)

        # Read-only by design: there is deliberately no POST/PUT handler.
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--demo', action='store_true', help='Simulated data, clearly labeled; no USB access')
    parser.add_argument('--port', type=int, default=8765, help='HTTP port on 127.0.0.1 (default 8765)')
    parser.add_argument('--controller-port', help=f'Override auto-detect (USB serial {CONTROLLER_SERIAL})')
    parser.add_argument('--boat-port', help=f'Override auto-detect (USB serial {BOAT_SERIAL})')
    parser.add_argument('--no-controller', action='store_true')
    parser.add_argument('--no-boat', action='store_true')
    parser.add_argument('--motor-voltage', type=float, default=6.0, help='Assumed motor rail; NOT measured')
    parser.add_argument('--center-x', type=int, default=1915)
    parser.add_argument('--center-y', type=int, default=1925)
    parser.add_argument('--deadzone', type=float, default=0.05)
    args = parser.parse_args()
    if not math.isfinite(args.motor_voltage) or args.motor_voltage <= 0:
        parser.error('--motor-voltage must be finite and positive')

    bridge = Bridge(args)
    worker = threading.Thread(target=bridge.run, daemon=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(bridge))
    server.daemon_threads = True
    worker.start()
    mode = 'SIMULATED data' if args.demo else 'live boards (read-only)'
    print(f'Poseidon web: http://127.0.0.1:{args.port}  [{mode}]  Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop.set()
        worker.join(timeout=2)
        server.server_close()
        print('Poseidon web closed; serial ports released.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
