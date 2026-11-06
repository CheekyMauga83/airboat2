"""Read-only desktop viewer for the Airboat controller's USB diagnostics."""
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import serial
from serial.tools import list_ports


def parse_line(line):
    match = re.search(r"X=\s*(\d+)\s+Y=\s*(\d+)\s+BUTTON=(PRESSED|released)", line)
    if not match:
        return None
    result = dict(x=int(match[1]), y=int(match[2]), button=match[3])
    for key in ("seq", "MAC_ACK", "FAIL", "pending"):
        field = re.search(rf"\b{key}=(\d+)", line)
        if field:
            result[key] = int(field[1])
    return result


class Monitor:
    def __init__(self, root):
        self.root = root
        root.title("Airboat • Controller feedback")
        root.geometry("820x780")
        self.events = queue.Queue(maxsize=1000)
        self.stop = threading.Event()
        self.worker = None
        self.last_sample = 0
        self.status = tk.StringVar(value="Disconnected — choose the controller USB port")
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Airboat controller", font=("Helvetica", 24, "bold")).pack(anchor="w")
        ttk.Label(frame, text="USB feedback • 115200 baud • raw ADC readings").pack(anchor="w", pady=(0, 15))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.port = tk.StringVar(value="/dev/cu.usbmodem101")
        self.ports = ttk.Combobox(row, textvariable=self.port, width=35)
        self.ports.pack(side="left")
        ttk.Button(row, text="Refresh ports", command=self.refresh).pack(side="left", padx=6)
        self.connect_button = ttk.Button(row, text="Connect", command=self.connect)
        self.connect_button.pack(side="left")
        ttk.Button(row, text="Disconnect", command=self.disconnect).pack(side="left", padx=6)
        ttk.Label(frame, textvariable=self.status, wraplength=750).pack(anchor="w", pady=12)
        self.canvas = tk.Canvas(frame, width=360, height=300, bg="#10232d", highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_rectangle(40, 20, 320, 280, outline="#547481")
        self.canvas.create_line(180, 20, 180, 280, fill="#547481")
        self.canvas.create_line(40, 150, 320, 150, fill="#547481")
        self.canvas.create_text(180, 10, text="FORWARD · Y=0", fill="white")
        self.canvas.create_text(180, 291, text="BACKWARD · Y=4095", fill="white")
        self.dot = self.canvas.create_oval(0, 0, 0, 0, fill="#48d6a5", outline="")
        self.values = tk.StringVar(value="X —     Y —     Button —")
        ttk.Label(frame, textvariable=self.values, font=("Helvetica", 18, "bold")).pack(pady=10)
        self.radio = tk.StringVar(value="Sequence —    MAC ACK —    Failed —    Pending —")
        ttk.Label(frame, textvariable=self.radio).pack()
        ttk.Label(frame, text="MAC ACK is radio delivery feedback; boat LINK OK confirms application receipt.", wraplength=750).pack(pady=(6, 12))
        self.log = ScrolledText(frame, height=9, font=("Menlo", 11), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)

    def refresh(self):
        self.ports["values"] = [p.device for p in list_ports.comports()]

    def connect(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop = threading.Event()
        self.last_sample = 0
        self.status.set("Opening " + self.port.get())
        self.connect_button.state(["disabled"])
        self.worker = threading.Thread(target=self.read, args=(self.port.get(), self.stop), daemon=True)
        self.worker.start()

    def emit(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            pass

    def read(self, port, stop):
        try:
            with serial.Serial(port, 115200, timeout=0.3) as connection:
                self.emit("status", "Connected — waiting for controller readings")
                while not stop.is_set():
                    line = connection.read_until(b"\n", 1024).decode(errors="replace").strip()
                    if line:
                        self.emit("line", line)
        except (serial.SerialException, OSError) as error:
            self.emit("status", "Connection error: " + str(error))
        finally:
            self.emit("done", None)

    def disconnect(self):
        self.stop.set()
        self.last_sample = 0
        self.status.set("Disconnected")
        self.canvas.itemconfigure(self.dot, fill="#73838a")

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status.set(value)
            elif kind == "done":
                self.connect_button.state(["!disabled"])
                self.last_sample = 0
                self.canvas.itemconfigure(self.dot, fill="#73838a")
            elif kind == "line":
                self.log.configure(state="normal")
                self.log.insert("end", value + "\n")
                if int(self.log.index("end-1c").split(".")[0]) > 250:
                    self.log.delete("1.0", "2.0")
                self.log.see("end")
                self.log.configure(state="disabled")
                data = parse_line(value)
                if data:
                    self.last_sample = time.monotonic()
                    self.status.set("Live controller feedback")
                    x = 40 + min(4095, data["x"]) / 4095 * 280
                    y = 20 + min(4095, data["y"]) / 4095 * 260
                    self.canvas.coords(self.dot, x-9, y-9, x+9, y+9)
                    self.canvas.itemconfigure(self.dot, fill="#ffc45c" if data["button"] == "PRESSED" else "#48d6a5")
                    self.values.set(f'X {data["x"]}     Y {data["y"]}     Button {data["button"]}')
                    self.radio.set("    ".join(f'{label} {data.get(key, "—")}' for key, label in (("seq", "Sequence"), ("MAC_ACK", "MAC ACK"), ("FAIL", "Failed"), ("pending", "Pending"))))
        if self.last_sample and time.monotonic() - self.last_sample > 2:
            self.status.set("No feedback for over 2 seconds — displayed values are stale")
            self.canvas.itemconfigure(self.dot, fill="#73838a")
        self.root.after(50, self.poll)

    def close(self):
        self.stop.set()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Monitor(root)
    root.mainloop()
