"""
WorldModel - Append-only event store for agent observations and actions.

Features:
- In-memory event deque for quick access
- Optional JSONL file persistence for durability
- Event replay for deterministic testing
- Agent-scoped event filtering
"""
import asyncio
import time
import json
import os
from typing import Callable, List, Dict, Any, Optional
from collections import deque
from datetime import datetime


class WorldModel:
    """
    Maintains a rolling history of events (tool calls, results, observations).
    Used for replay, debugging, and providing context to agents.
    
    Optionally persists events to JSONL file for durability.
    """

    def __init__(self, max_events: int = 1000, persist_path: Optional[str] = None):
        """
        Initialize the world model.
        
        Args:
            max_events: Maximum events to keep in memory
            persist_path: If provided, append events to this JSONL file
        """
        self.events = deque(maxlen=max_events)
        self.max_events = max_events
        self.persist_path = persist_path
        self.call_id_counter = 0
        self._listeners: List[Callable[[Dict[str, Any]], Any]] = []

        if self.persist_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.persist_path)), exist_ok=True)
            logger.info(f"WorldModel persistence enabled: {self.persist_path}")

    def subscribe(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Register a callback to be notified of every event as it's appended.
        This is what makes the world model an actual event bus rather than
        just a log: reflexes and other plugins react in real time instead of
        polling. Callback may be sync or async — an async callback (a
        coroutine function) is scheduled as a task rather than awaited
        in-line, so a slow listener can never block the tool-call path that
        produced the event.

        Args:
            callback: Called with the event dict on every append_event()
        """
        self._listeners.append(callback)

    def _notify_listeners(self, event: Dict[str, Any]) -> None:
        for callback in self._listeners:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    try:
                        asyncio.get_running_loop()
                        asyncio.create_task(result)
                    except RuntimeError:
                        # No running loop (e.g. called from sync code/tests) —
                        # nothing to schedule the coroutine on, so drop it
                        # rather than block append_event with asyncio.run().
                        logger.warning(
                            "WorldModel listener returned a coroutine with no "
                            "running event loop; skipping it"
                        )
                        result.close()
            except Exception as e:
                logger.error(f"WorldModel listener error: {e}")

    def append_event(self, event: Dict[str, Any]) -> None:
        """
        Append an event to the history, optionally persist it, and notify
        any subscribed listeners (see subscribe()).

        Args:
            event: Dictionary containing event data. Should include:
                - timestamp: float (epoch seconds) - auto-added if missing
                - type: str (e.g., "tool_call", "tool_result")
                - agent_id: str
                - call_id: str (optional)
                - Additional event-specific fields
        """
        if "timestamp" not in event:
            event["timestamp"] = time.time()

        if "call_id" not in event:
            self.call_id_counter += 1
            event["call_id"] = f"event-{self.call_id_counter}"

        self.events.append(event)

        # Persist to JSONL if configured
        if self.persist_path:
            self._persist_event(event)

        self._notify_listeners(event)

    def record_sensor_reading(
        self, sensor_name: str, value: Any, agent_id: str = "sensor", **extra: Any
    ) -> None:
        """
        Convenience wrapper for the event shape reflex-style listeners expect
        (a flat "sensor_name"/"value" pair) — sensors should call this rather
        than building a "sensor_reading" event dict by hand.
        """
        self.append_event({
            "type": "sensor_reading",
            "agent_id": agent_id,
            "sensor_name": sensor_name,
            "value": value,
            **extra,
        })

    def _persist_event(self, event: Dict[str, Any]) -> None:
        """Write event to JSONL file."""
        try:
            with open(self.persist_path, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except IOError as e:
            logger.error(f"Failed to persist event: {e}")

    def get_recent(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve the N most recent events.
        
        Args:
            n: Number of recent events to return
            
        Returns:
            List of event dictionaries, most recent last
        """
        return list(self.events)[-n:]

    def get_events_for_agent(self, agent_id: str, n: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent events for a specific agent.
        
        Args:
            agent_id: Agent identifier
            n: Number of events to return
            
        Returns:
            List of events matching agent_id, most recent last
        """
        return [e for e in list(self.events)[-n:] if e.get("agent_id") == agent_id]

    def get_events_by_type(self, event_type: str, n: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent events of a specific type.
        
        Args:
            event_type: Type of events to filter (e.g., "tool_call")
            n: Number of events to return
            
        Returns:
            List of events matching type, most recent last
        """
        return [e for e in list(self.events)[-n:] if e.get("type") == event_type]

    def load_from_jsonl(self, path: str) -> int:
        """
        Load events from JSONL file for replay.
        
        Args:
            path: Path to JSONL file
            
        Returns:
            Number of events loaded
        """
        count = 0
        try:
            with open(path, 'r') as f:
                for line in f:
                    if line.strip():
                        event = json.loads(line)
                        self.events.append(event)
                        count += 1
            logger.info(f"Loaded {count} events from {path}")
            return count
        except IOError as e:
            logger.error(f"Failed to load events: {e}")
            return 0

    def get_all(self) -> List[Dict[str, Any]]:
        """Get all events in memory."""
        return list(self.events)

    def clear(self) -> None:
        """Clear all events from memory."""
        self.events.clear()
        logger.info("WorldModel cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about events."""
        events_list = list(self.events)
        
        agent_ids = set(e.get("agent_id") for e in events_list if "agent_id" in e)
        event_types = {}
        for e in events_list:
            etype = e.get("type", "unknown")
            event_types[etype] = event_types.get(etype, 0) + 1
        
        return {
            "total_events": len(events_list),
            "max_capacity": self.max_events,
            "unique_agents": len(agent_ids),
            "event_types": event_types,
            "persisted": self.persist_path is not None,
        }


# Simple logging for this module
import logging
logger = logging.getLogger(__name__)
