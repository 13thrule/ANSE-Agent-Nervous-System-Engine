#!/usr/bin/env python3
"""
ANSE WebSocket Backend, driven by the real Arduino Mega instead of the
simulated distance sensor.

Same dashboard, same reflex_system, same wire protocol as
websocket_backend.py -- the only thing that changes is where distance_cm
and temperature_c/humidity_pct come from, and movement_stop/resume now
drive the real servo + LED over serial instead of just tracking state.

Usage:
    python backend/websocket_backend_hardware.py --port COM8
"""
import argparse
import asyncio
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import serial

from backend.websocket_backend import ANSEWebSocketBackend

STOP_THRESHOLD_CM = 10
RESUME_THRESHOLD_CM = 15
FLAME_THRESHOLD_C = 34


def serial_reader_thread(
    ser: "serial.Serial",
    out_queue: "queue.Queue[tuple[str, float]]",
    stop_event: threading.Event,
) -> None:
    """Runs on its own thread -- pyserial's readline() blocks."""
    while not stop_event.is_set():
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
        except serial.SerialException:
            break
        if line.startswith("D,"):
            try:
                out_queue.put(("distance_cm", float(line[2:])))
            except ValueError:
                pass
        elif line.startswith("T,"):
            try:
                temp_str, humidity_str = line[2:].split(",")
                out_queue.put(("temperature_c", float(temp_str)))
                out_queue.put(("humidity_pct", float(humidity_str)))
            except ValueError:
                pass


class HardwareANSEBackend(ANSEWebSocketBackend):
    def __init__(self, ser: "serial.Serial", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ser = ser
        self._reading_queue: "queue.Queue[tuple[str, float]]" = queue.Queue()
        self._stop_event = threading.Event()

    async def initialize_engine(self) -> bool:
        ok = await super().initialize_engine()
        if not ok:
            return ok

        reflex = self.engine.plugins.get("reflex_system")
        if reflex:
            await reflex.add_reflex(
                sensor_name="temperature_c",
                threshold=FLAME_THRESHOLD_C,
                comparison="greater_than",
                action_tool="movement_stop",
                action_args={"reason": f"temperature above {FLAME_THRESHOLD_C}C"},
            )
            self._log("✓ reflex_system: flame/heat reflex armed (reuses movement_stop)")
        return ok

    async def _movement_stop(self, reason: str = "") -> dict:
        self.ser.write(b"ALARM\n" if "temperature" in reason else b"STOP\n")
        return await super()._movement_stop(reason)

    async def _movement_resume(self, reason: str = "") -> dict:
        self.ser.write(b"HOME\n")
        return await super()._movement_resume(reason)

    async def simulate_distance_sensor(self):
        """Overrides the simulated loop -- reads the real Arduino instead."""
        self._log("[SENSOR] Reading real HC-SR04 + DHT11 over serial")
        reader = threading.Thread(
            target=serial_reader_thread,
            args=(self.ser, self._reading_queue, self._stop_event),
            daemon=True,
        )
        reader.start()

        while True:
            try:
                sensor_name, value = self._reading_queue.get(timeout=0.5)
            except queue.Empty:
                await asyncio.sleep(0)
                continue
            if sensor_name == "distance_cm":
                self.distance = value
            self.engine.world.record_sensor_reading(sensor_name, value)
            await asyncio.sleep(0)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Arduino serial port, e.g. COM8")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--ws-port", type=int, default=8001)
    args = parser.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=1)
    print(f"Opened {args.port} @ {args.baud} -- waiting for the Mega to reboot...")
    await asyncio.sleep(2)

    backend = HardwareANSEBackend(ser, host="0.0.0.0", port=args.ws_port, debug=False)
    await backend.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nBackend stopped")
