"""
Arduino hardware demo.

Same reflex wiring as examples/reflex_bus_demo.py — EngineCore, the real
reflex_system plugin, add_reflex(), record_sensor_reading() — except the
distance_cm reading now comes from a real HC-SR04 on an Arduino (flash
examples/arduino/anse_reflex_demo/anse_reflex_demo.ino first) instead of a
simulated loop, and emergency_stop drives a real servo instead of just
printing. temperature_c and humidity_pct come from the same board's DHT11.

Run:  python -u examples/arduino_hardware_demo.py --port COM3
(the -u is needed on Windows — stdout is fully buffered when not attached
to a terminal, so prints don't appear live otherwise)
"""
import argparse
import asyncio
import os
import queue
import sys
import threading

import serial

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anse.engine_core import EngineCore

STOP_THRESHOLD_CM = 10
FLAME_THRESHOLD_C = 34


def serial_reader_thread(
    ser: "serial.Serial",
    out_queue: "queue.Queue[tuple[str, float]]",
    stop_event: threading.Event,
) -> None:
    """Runs on its own thread — pyserial's readline() blocks, so it can't live on the asyncio loop."""
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


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Arduino serial port, e.g. COM3")
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=1)
    print(f"Opened {args.port} @ {args.baud} — waiting for the Mega to reboot...")
    await asyncio.sleep(2)  # opening the port resets the Mega; let it boot before reading

    core = EngineCore(simulate=True)

    async def emergency_stop(reason: str = "") -> dict:
        ser.write(b"STOP\n")
        print(f"    \U0001F6D1 emergency_stop fired -- {reason}")
        return {"status": "stopped", "reason": reason}

    core.register_tool(
        name="emergency_stop",
        func=emergency_stop,
        description="Immediately park the servo and light the onboard LED",
        parameters={"reason": {"type": "string"}},
        sensitivity="high",
        cost_hint={"latency_ms": 10},
    )

    async def flame_alert(reason: str = "") -> dict:
        ser.write(b"ALARM\n")
        print(f"    \U0001F525 flame_alert fired -- {reason}")
        return {"status": "alarmed", "reason": reason}

    core.register_tool(
        name="flame_alert",
        func=flame_alert,
        description="Sweep the servo and blink the LED to signal a flame/heat spike",
        parameters={"reason": {"type": "string"}},
        sensitivity="high",
        cost_hint={"latency_ms": 10},
    )

    reflex = core.plugins.get("reflex_system")
    if reflex is None:
        print("reflex_system plugin did not load -- check plugins/system/reflex_system/")
        ser.close()
        return

    added = await reflex.add_reflex(
        sensor_name="distance_cm",
        threshold=STOP_THRESHOLD_CM,
        comparison="less_than",
        action_tool="emergency_stop",
        action_args={"reason": f"object within {STOP_THRESHOLD_CM}cm"},
    )
    print(f"reflex configured: {added}")

    added_flame = await reflex.add_reflex(
        sensor_name="temperature_c",
        threshold=FLAME_THRESHOLD_C,
        comparison="greater_than",
        action_tool="flame_alert",
        action_args={"reason": f"temperature above {FLAME_THRESHOLD_C}C"},
    )
    print(f"reflex configured: {added_flame}")

    await reflex.enable_background_monitoring()

    reading_queue: "queue.Queue[tuple[str, float]]" = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=serial_reader_thread, args=(ser, reading_queue, stop_event), daemon=True
    )
    reader.start()

    print(f"\nListening on {args.port} -- move your hand toward the HC-SR04.")
    print(f"Reflex fires under {STOP_THRESHOLD_CM}cm. Ctrl+C to quit.\n")

    try:
        while True:
            try:
                sensor_name, value = reading_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            print(f"  sensor -> {sensor_name} = {value}")
            core.world.record_sensor_reading(sensor_name, value)
            await asyncio.sleep(0)  # yield so the scheduled reflex task actually runs
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        ser.write(b"HOME\n")
        ser.close()
        status = await reflex.list_reflexes()
        for r in status["reflexes"]:
            print(f"reflex {r['sensor_name']}: {r['triggered_count']} trigger(s) fired")


if __name__ == "__main__":
    asyncio.run(main())
