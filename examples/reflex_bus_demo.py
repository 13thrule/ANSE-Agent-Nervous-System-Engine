"""
Reflex bus demo.

Proves the world model is a real event bus, not just a log: a simulated
distance sensor reports readings, and the reflex_system plugin — subscribed
automatically by EngineCore at startup — reacts and fires an actuator action
the instant a threshold is crossed, with no LLM/agent in the loop at all.

Run:  python examples/reflex_bus_demo.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anse.engine_core import EngineCore


async def emergency_stop(reason: str = "") -> dict:
    print(f"    🛑 emergency_stop fired — {reason}")
    return {"status": "stopped", "reason": reason}


async def main():
    core = EngineCore(simulate=True)

    core.register_tool(
        name="emergency_stop",
        func=emergency_stop,
        description="Immediately halt actuator motion",
        parameters={"reason": {"type": "string"}},
        sensitivity="high",
        cost_hint={"latency_ms": 10},
    )

    reflex = core.plugins.get("reflex_system")
    if reflex is None:
        print("reflex_system plugin did not load — check plugins/system/reflex_system/")
        return

    added = await reflex.add_reflex(
        sensor_name="distance_cm",
        threshold=10,
        comparison="less_than",
        action_tool="emergency_stop",
        action_args={"reason": "object within 10cm"},
    )
    print(f"reflex configured: {added}")
    await reflex.enable_background_monitoring()

    print("\nfeeding simulated distance_cm readings through the world model:\n")
    readings = [50, 30, 15, 8, 5, 20]
    for value in readings:
        print(f"  sensor -> distance_cm = {value}")
        core.world.record_sensor_reading("distance_cm", value)
        await asyncio.sleep(0.05)  # let the scheduled reflex task actually run

    await asyncio.sleep(0.1)

    status = await reflex.list_reflexes()
    print(f"\nreflex status: {status['reflexes'][0]['triggered_count']} trigger(s) fired")

    print("\nworld model event log (proves it all went through one real bus):")
    for event in core.world.get_recent(30):
        etype = event.get("type")
        if etype == "sensor_reading":
            print(f"  [{etype}] {event['sensor_name']} = {event['value']}")
        elif etype in ("tool_call", "tool_result"):
            print(f"  [{etype}] {event.get('tool', '')} {event.get('result', '')}".rstrip())


if __name__ == "__main__":
    asyncio.run(main())
