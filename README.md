# ANSE — Agent Nervous System Engine

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

**A local runtime that gives an agent a body — and, critically, reflexes.**

ANSE connects an agent (an LLM, a script, anything that can hold a WebSocket
connection) to sensors and actuators. It's built around one specific idea:
**safety-critical reactions shouldn't have to wait for the agent to think.**

---

## The idea

Pull your hand off a hot stove and you'll notice something: you were already
moving before you consciously registered the pain. That's a spinal reflex
arc — a fast, hard-wired circuit that reacts to a threshold being crossed
without waiting for your brain to finish deliberating. Your brain finds out
what happened *after the fact*, from the same nerve signal that triggered
the reflex.

Most "agent + hardware" setups don't have this. The LLM is in the loop for
*everything* — read the sensor, reason about it, decide, act — which means
the safety-critical path is only as fast and as reliable as the slowest,
least deterministic part of the whole system: the model's own reasoning
loop. If the model hangs, hallucinates, or just takes 4 seconds to respond,
there's a 4-second window where nothing stops the robot arm, nothing shuts
off the motor, nothing happens.

ANSE splits the loop in two:

- **The reflex path** — deterministic, sub-second, no LLM involved. A sensor
  reading crosses a threshold, a reflex fires, an actuator responds. This is
  the part that has to be reliable.
- **The deliberate path** — the agent reads the world model (the same event
  stream the reflexes react to) and makes the slower, judgment-based calls:
  what to do next, how to respond to a user, when to change strategy.

The agent still sees everything, including what the reflexes did — the same
way your brain finds out you flinched. It just isn't on the critical path
for the reaction itself.

---

## How the pieces map to a nervous system

This isn't decorative — each plugin category is a specific, real analogue,
and (as of this rewrite) each one actually does what its name says:

| Nervous system | ANSE component | What it actually does |
|---|---|---|
| Sensory receptors | `plugins/sensors/` | Sensor plugins — camera, mic, or custom hardware via YAML/Python |
| Spinal reflex arc | `plugins/system/reflex_system/` | Watches the world model event bus; fires an actuator tool directly when a sensor crosses a threshold — no agent involved |
| Motor output | `plugins/actuators/motor_control/` | Wheel/servo control, with safety limits and rate limiting |
| Proprioception | `plugins/cognition/body_schema/` | A self-model: what sensors/actuators/joints exist and what they can do |
| Memory consolidation | `plugins/cognition/long_term_memory/` | Persistent storage beyond the rolling event log |
| Motivation / reinforcement | `plugins/cognition/reward_system/` | Reward tracking over time |
| The state the brain reasons over | `anse/world_model.py` | An append-only event log **and** a real pub/sub event bus — see below |
| An EEG probe for a human operator | `plugins/system/dashboard_bridge/` | Read-focused bridge exposing live state to the web dashboard |

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │   Sensors (real or simulated)│
                    └───────────────┬─────────────┘
                                    │ world.record_sensor_reading(...)
                                    ▼
                    ┌─────────────────────────────┐
                    │   World Model (event bus)    │  ← anse/world_model.py
                    │   append_event() → notifies  │
                    │   every subscriber, live      │
                    └───────┬───────────────┬──────┘
              (fast path)   │               │   (slow path)
                            ▼               ▼
              ┌───────────────────┐   ┌─────────────────────┐
              │  reflex_system     │   │   Your agent         │
              │  plugin — reacts   │   │   (LLM / script),     │
              │  to a threshold,   │   │   connected over       │
              │  calls an actuator │   │   WebSocket, reads      │
              │  tool directly     │   │   world-model events    │
              │  (sub-second,      │   │   and decides the        │
              │  no agent in the   │   │   slower stuff            │
              │  loop)             │   │                            │
              └─────────┬──────────┘   └────────────┬───────────────┘
                        │                            │
                        ▼                            ▼
              ┌─────────────────────────────────────────────┐
              │              Actuators (tool_registry)        │
              └─────────────────────────────────────────────┘
```

The event bus (`WorldModel.subscribe()`) is what makes this real rather than
aspirational: `EngineCore` automatically subscribes any plugin that
implements `process_world_model_event()` when it loads, so a reflex reacts
to a sensor reading the instant it's recorded — not on a poll, not on the
next agent turn.

---

## Quick start

```bash
pip install -r requirements.txt

# Terminal demo — proves the reflex bus works with no UI at all
python examples/reflex_bus_demo.py

# Live dashboard — watch reflexes fire in a browser in real time
python backend/websocket_backend.py        # terminal 1: engine + WebSocket
cd dashboard && python -m http.server 8002 # terminal 2: static dashboard
# open http://localhost:8002
```

The dashboard connects to `ws://localhost:8001` and shows a simulated
distance sensor approaching and receding. When it crosses 10cm, the real
`reflex_system` plugin fires a `movement_stop` actuator call — you'll see
the World Model panel flip to `STOPPED`, the reflex show up in the event
log, and the whole thing recover automatically once the sensor clears 15cm.
Nothing in that loop is hardcoded to the dashboard; the same event bus
drives both the terminal demo and the browser view.

---

## Building a reflex

This is the actual API a reflex is built from — no YAML DSL, just a direct
call against the loaded plugin:

```python
core = EngineCore(simulate=True)

core.register_tool(
    name="emergency_stop",
    func=my_stop_function,
    description="Immediately halt actuator motion",
    parameters={"reason": {"type": "string"}},
    sensitivity="high",
    cost_hint={"latency_ms": 10},
)

reflex = core.plugins["reflex_system"]
await reflex.add_reflex(
    sensor_name="distance_cm",
    threshold=10,
    comparison="less_than",
    action_tool="emergency_stop",
    action_args={"reason": "object within 10cm"},
)
await reflex.enable_background_monitoring()

# From here on, every core.world.record_sensor_reading("distance_cm", v)
# is checked against this rule automatically — no polling, no agent call.
```

---

## Plugins

Two ways to extend ANSE, both auto-discovered recursively from `plugins/`
(category subfolders — `sensors/`, `actuators/`, `cognition/`, `system/`):

- **YAML plugins** — a config file with inline handler code. No Python
  packaging, good for simple integrations. See `plugins/sensors/_template_sensor.yaml`.
- **Python plugins** — a class with `name`/`description` and public async
  methods. Every public async method is automatically registered as a
  callable tool (`{plugin_name}_{method_name}`); any method named
  `process_world_model_event(event, engine)` is automatically subscribed to
  the world model's event bus.

See [docs/PLUGINS.md](docs/PLUGINS.md) for the full guide.

---

## Where this stands right now

Being direct about this, because the gap between "described in the docs"
and "actually wired up" is exactly what this rewrite exists to close.

### Real, and proven working today
- **The event bus.** `WorldModel.subscribe()` + notification on every
  `append_event()`. Confirmed live: fed simulated sensor readings through
  it and watched `reflex_system` fire an actuator call with no agent
  involved, both from a terminal script and from the browser dashboard.
- **Plugin discovery and registration.** Both were silently broken before
  this pass — discovery only checked the top level of `plugins/` (missed
  everything in the category subfolders), and registration threw on every
  single plugin it did find (an `asyncio.run()` inside an already-running
  loop for YAML plugins, a signature-iteration bug for Python plugins).
  Fixed; going from 0 usable plugin tools to 60.
- **The dashboard.** The backend and frontend didn't agree on the wire
  protocol, and the frontend's own event router checked for the wrong type
  strings — so only the raw event log ever worked; the World Model, Sensor,
  Actuator, and Reflex panels were dead on arrival. Fixed; the dashboard
  now reflects real reflex firings live.
- **Rate limiting** (`anse/scheduler.py`) — was already real, unaffected by
  any of the above.

### Exists, but not wired up yet — known, not hidden
- **`anse/safety/permission.py`** (scopes, human-approval-required lists) is
  fully implemented but never actually called from the tool-execution path.
  Right now it's decorative — nothing currently enforces a scope or blocks
  an unapproved tool call.
- **Declarative safety rules** (a YAML `if: / then: deny` style DSL) don't
  exist as a parser anywhere in the codebase. The real, working equivalent
  is `reflex_system.add_reflex()` above — imperative, not declarative, but
  actually functional.
- The sandboxed filesystem/network tools (`anse/tools/filesystem.py`,
  `network.py`) haven't been re-audited as part of this pass — treat them
  as unverified until someone does.

### Tests
`pytest tests/ -q --ignore=tests/test_operator_ui.py` → 60 passed, 2 failed
(both because `opencv-python` isn't installed in the dev environment, not a
code issue), 16 skipped. `test_operator_ui.py` imports a module
(`operator_ui`) that doesn't exist in this repo and needs to either be
removed or have that subsystem actually built.

---

## Project layout

```
anse/                    core engine — world model, tool registry, scheduler,
                          plugin loader, safety policy, agent bridge
plugins/
  sensors/                sensor plugins (YAML + Python)
  actuators/               motor control, etc.
  cognition/                body_schema, long_term_memory, reward_system
  system/                    reflex_system, dashboard_bridge
backend/websocket_backend.py  live demo: real engine + WebSocket + dashboard feed
dashboard/                    browser UI — vanilla JS, zero build step
examples/reflex_bus_demo.py   terminal-only proof the event bus works
tests/                         pytest suite
docs/                           API.md, PLUGINS.md, DESIGN.md, etc.
```

---

## License

MIT — see [LICENSE](LICENSE).
