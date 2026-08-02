"""
Reflex System Plugin for ANSE

Enables fast, non-LLM reactions to sensor thresholds without calling an LLM.
Useful for emergency responses and simple reactive behaviors.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ReflexSystemPlugin:
    """Implements fast reflex reactions to sensor thresholds."""

    name = "reflex_system"
    description = "Fast, non-LLM reflex actions triggered by sensor thresholds"
    version = "1.0.0"

    def __init__(self):
        """Initialize reflex system."""
        self.reflexes: Dict[str, Dict[str, Any]] = {}
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None

    async def add_reflex(
        self,
        sensor_name: str,
        threshold: float,
        comparison: str,
        action_tool: str,
        action_args: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add a reflex rule.

        Args:
            sensor_name: Name of sensor to monitor
            threshold: Threshold value
            comparison: 'greater_than', 'less_than', or 'equal_to'
            action_tool: Tool to call when threshold is crossed
            action_args: Arguments for the action tool

        Returns:
            Reflex configuration dict with ID
        """
        reflex_id = str(uuid.uuid4())[:8]

        if comparison not in ["greater_than", "less_than", "equal_to"]:
            return {"status": "error", "message": "Invalid comparison operator"}

        self.reflexes[reflex_id] = {
            "id": reflex_id,
            "sensor_name": sensor_name,
            "threshold": float(threshold),
            "comparison": comparison,
            "action_tool": action_tool,
            "action_args": action_args or {},
            "created_at": datetime.now().isoformat(),
            "triggered_count": 0,
            # Edge-triggered state: True once the condition has fired and
            # hasn't cleared yet, so a sensor sitting past the threshold
            # across many readings only fires the action once per crossing
            # instead of once per reading.
            "active": False
        }

        logger.info(f"[REFLEX] Added reflex {reflex_id}: {sensor_name} {comparison} {threshold} → {action_tool}")

        return {
            "status": "success",
            "reflex_id": reflex_id,
            "message": f"Reflex {reflex_id} added"
        }

    async def list_reflexes(self) -> Dict[str, Any]:
        """
        List all active reflexes.

        Returns:
            Dict with status and list of reflex configurations
        """
        return {
            "status": "success",
            "reflexes": list(self.reflexes.values()),
            "count": len(self.reflexes)
        }

    async def remove_reflex(self, reflex_id: str) -> Dict[str, Any]:
        """
        Remove a reflex rule by ID.

        Args:
            reflex_id: ID of reflex to remove

        Returns:
            Confirmation dict
        """
        if reflex_id in self.reflexes:
            del self.reflexes[reflex_id]
            logger.info(f"[REFLEX] Removed reflex {reflex_id}")
            return {"status": "success", "message": f"Reflex {reflex_id} removed"}
        else:
            return {"status": "error", "message": f"Reflex {reflex_id} not found"}

    async def enable_background_monitoring(self) -> Dict[str, Any]:
        """
        Start background monitoring loop (run once per engine).

        Returns:
            Status dict
        """
        if self.monitoring:
            return {"status": "already_running", "message": "Monitoring already active"}

        self.monitoring = True
        logger.info("[REFLEX] Background monitoring enabled")

        # Note: In a real implementation, this would start a long-running background task
        # For now, just return success. The actual monitoring would be integrated
        # with the ANSE engine's event loop.

        return {
            "status": "success",
            "message": "Background monitoring enabled"
        }

    async def process_world_model_event(self, event: Dict[str, Any], engine: Any) -> None:
        """
        React to world model events and trigger reflexes if thresholds are crossed.
        This is event-driven, not polling-based.

        Args:
            event: World model event
            engine: Reference to ANSE engine for tool calling
        """
        if not self.monitoring:
            return
        
        try:
            # Extract sensor reading from event if available
            sensor_name = event.get("sensor_name")
            sensor_value = event.get("value")
            
            if sensor_name is None or sensor_value is None:
                return
            
            # Check all reflexes for this sensor
            for reflex_id, reflex in self.reflexes.items():
                if reflex["sensor_name"] != sensor_name:
                    continue
                
                # Check threshold
                triggered = False
                if reflex["comparison"] == "greater_than":
                    triggered = sensor_value > reflex["threshold"]
                elif reflex["comparison"] == "less_than":
                    triggered = sensor_value < reflex["threshold"]
                elif reflex["comparison"] == "equal_to":
                    triggered = abs(sensor_value - reflex["threshold"]) < 0.01
                
                # Fire only on the rising edge -- a sensor sitting past the
                # threshold across many readings should trigger the action
                # once per crossing, not once per reading. Resetting "active"
                # the moment the condition clears means the next crossing
                # still fires for real; this isn't a cooldown or a rate
                # limit, just de-duplication of one continuous event.
                if triggered and not reflex["active"]:
                    reflex["active"] = True
                    logger.info(f"[REFLEX] Triggered {reflex_id}: {reflex['action_tool']}({reflex['action_args']})")
                    try:
                        await engine.tools.call(reflex["action_tool"], reflex["action_args"])
                        reflex["triggered_count"] += 1
                    except Exception as e:
                        logger.error(f"[REFLEX] Failed to execute action {reflex['action_tool']}: {e}")
                elif not triggered:
                    reflex["active"] = False
        except Exception as e:
            logger.error(f"[REFLEX] Event processing error: {e}")
