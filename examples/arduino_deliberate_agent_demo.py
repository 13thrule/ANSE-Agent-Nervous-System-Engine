"""
Deliberate-path demo — the other half of ANSE, proven on real hardware.

Every other hardware example proves the reflex path: sub-second, no LLM,
fires directly off the world model event bus. This one proves the
deliberate path instead — the thing that actually makes ANSE about
grounding an agent in physical consequence, not just a safety framework.

Same setup as arduino_hardware_demo.py (real HC-SR04 + DHT11 over serial,
a real reflex_system reflex wired to emergency_stop), but after watching
telemetry for a while, the script does what a deliberating agent does:
reads the world model's own event log *after the fact* — the same way you
find out you flinched — computes what actually happened, and takes its
own separate action (speaking a summary via the `say` tool) distinct from
whatever the reflex already did on its own.

In this script that reasoning step is simple arithmetic (min distance
seen, how many times the reflex fired, humidity range) so the demo is
reproducible without an API key. Swap that block for an actual LLM call —
hand it `core.world.get_recent(n)` and let it decide what to say or do —
and this becomes the real thing: an agent narrating and acting on physical
events it did not control, the same architecture, no other changes.

Flash examples/arduino/anse_reflex_demo/anse_reflex_demo.ino first.

Run:  python -u examples/arduino_deliberate_agent_demo.py --port COM3
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
WATCH_SECONDS = 25


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
    await asyncio.sleep(2)

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

    reflex = core.plugins.get("reflex_system")
    if reflex is None:
        print("reflex_system plugin did not load -- check plugins/system/reflex_system/")
        ser.close()
        return

    await reflex.add_reflex(
        sensor_name="distance_cm",
        threshold=STOP_THRESHOLD_CM,
        comparison="less_than",
        action_tool="emergency_stop",
        action_args={"reason": f"object within {STOP_THRESHOLD_CM}cm"},
    )
    await reflex.enable_background_monitoring()

    reading_queue: "queue.Queue[tuple[str, float]]" = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=serial_reader_thread, args=(ser, reading_queue, stop_event), daemon=True
    )
    reader.start()

    print(f"\nWatching real telemetry for {WATCH_SECONDS}s -- the reflex path is live")
    print(f"(distance < {STOP_THRESHOLD_CM}cm stops the servo on its own, no LLM).")
    print("Move your hand around, breathe on the DHT11 if you want. I'm not")
    print("controlling anything yet -- just recording what happens.\n")

    end_time = asyncio.get_event_loop().time() + WATCH_SECONDS
    while asyncio.get_event_loop().time() < end_time:
        try:
            sensor_name, value = reading_queue.get(timeout=0.3)
        except queue.Empty:
            continue
        core.world.record_sensor_reading(sensor_name, value)
        await asyncio.sleep(0)  # yield so the scheduled reflex task actually runs

    stop_event.set()

    # --- The deliberate path starts here ---
    # Everything above was the reflex path proving itself, same as every
    # other hardware demo. This is the part that's new: reading the event
    # log *after the fact* and deciding what to say about it, separate from
    # whatever the reflex already did on its own.
    events = core.world.get_recent(1000)
    distances = [e["value"] for e in events if e.get("sensor_name") == "distance_cm"]
    humidities = [e["value"] for e in events if e.get("sensor_name") == "humidity_pct"]
    reflex_status = await reflex.list_reflexes()
    trigger_count = reflex_status["reflexes"][0]["triggered_count"] if reflex_status["reflexes"] else 0

    if distances:
        summary = (
            f"I watched {len(distances)} distance readings over {WATCH_SECONDS} seconds. "
            f"Closest approach was {min(distances):.1f} centimeters. "
            f"The stop reflex fired {trigger_count} time{'s' if trigger_count != 1 else ''} on its own, "
            f"before I said anything."
        )
        if humidities:
            summary += f" Humidity ranged from {min(humidities):.0f} to {max(humidities):.0f} percent."
    else:
        summary = "I didn't see any distance readings come through — check the wiring or the COM port."

    print(f"\n{summary}\n")
    await core.tools.call("say", {"text": summary})

    ser.write(b"HOME\n")
    ser.close()


if __name__ == "__main__":
    asyncio.run(main())
