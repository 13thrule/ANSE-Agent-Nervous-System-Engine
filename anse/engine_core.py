"""
EngineCore - Main orchestrator for ANSE.
Initializes all subsystems and starts the agent bridge.
"""
import asyncio
import logging
import os
from typing import Optional

from anse.tool_registry import ToolRegistry
from anse.scheduler import Scheduler
from anse.world_model import WorldModel
from anse.agent_bridge import AgentBridge
from anse.safety.permission import PermissionManager
from anse.health import initialize_health_monitor
from anse.plugin_loader import PluginLoader

# Import tool implementations
from anse.tools.video import capture_frame, list_cameras
from anse.tools.audio import record_audio, list_audio_devices
from anse.tools.tts import say, get_voices

# Import simulated tools (conditional loading)
try:
    from anse.tools.simulated import (
        simulate_camera,
        simulate_microphone,
        list_cameras_sim,
        list_audio_devices_sim
    )
    SIMULATED_TOOLS_AVAILABLE = True
except ImportError:
    SIMULATED_TOOLS_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EngineCore:
    """
    Main ANSE engine that coordinates all subsystems.
    """

    def __init__(self, policy_path: Optional[str] = None, simulate: Optional[bool] = None):
        """
        Initialize the engine with all subsystems.
        
        Args:
            policy_path: Path to safety policy YAML file
            simulate: Force simulation mode. If None, checks ANSE_SIMULATE env var.
        """
        logger.info("Initializing ANSE Engine Core")
        
        # Determine sim mode
        if simulate is None:
            simulate = os.getenv("ANSE_SIMULATE", "").lower() in ("1", "true", "yes")
        
        self.simulate = simulate
        if self.simulate:
            logger.info("✓ Running in SIMULATED mode (hardware-free)")
        
        # Initialize health monitor
        self.health = initialize_health_monitor()
        
        # Initialize subsystems
        self.tools = ToolRegistry()
        self.world = WorldModel()
        self.permissions = PermissionManager(policy_path)
        self.scheduler = Scheduler(self.tools, self.world)
        self.bridge = AgentBridge(self.tools, self.world, self.scheduler, self.permissions)
        
        # Register built-in tools
        self._register_tools()
        
        # Load and register plugins
        self._load_plugins()
        
        # Configure rate limits from policy
        self._configure_rate_limits()
        
        logger.info("ANSE Engine Core initialized successfully")

    def _register_tools(self) -> None:
        """Register all built-in tools with the registry."""
        logger.info("Registering built-in tools")
        
        if self.simulate and SIMULATED_TOOLS_AVAILABLE:
            # Register simulated tools
            self.tools.register(
                name="capture_frame",
                func=simulate_camera,
                schema={
                    "type": "object",
                    "properties": {
                        "camera_id": {"type": "integer", "default": 0},
                        "width": {"type": "integer", "default": 640},
                        "height": {"type": "integer", "default": 480},
                        "seed": {"type": "integer"}
                    }
                },
                description="[SIMULATED] Capture deterministic frame from virtual camera",
                sensitivity="medium",
                cost_hint={"latency_ms": 50, "expensive": False}
            )
            
            self.tools.register(
                name="list_cameras",
                func=list_cameras_sim,
                schema={"type": "object", "properties": {}},
                description="[SIMULATED] List virtual camera devices",
                sensitivity="low",
                cost_hint={"latency_ms": 10, "expensive": False}
            )
            
            self.tools.register(
                name="record_audio",
                func=simulate_microphone,
                schema={
                    "type": "object",
                    "properties": {
                        "duration": {"type": "number", "default": 2.0, "minimum": 0.1, "maximum": 60},
                        "samplerate": {"type": "integer", "default": 16000},
                        "channels": {"type": "integer", "default": 1},
                        "seed": {"type": "integer"}
                    }
                },
                description="[SIMULATED] Record deterministic audio from virtual microphone",
                sensitivity="medium",
                cost_hint={"latency_ms": 100, "expensive": False}
            )
            
            self.tools.register(
                name="list_audio_devices",
                func=list_audio_devices_sim,
                schema={"type": "object", "properties": {}},
                description="[SIMULATED] List virtual audio devices",
                sensitivity="low",
                cost_hint={"latency_ms": 10, "expensive": False}
            )
        else:
            # Register real tools
            self.tools.register(
                name="capture_frame",
                func=capture_frame,
                schema={
                    "type": "object",
                    "properties": {
                        "camera_id": {"type": "integer", "default": 0},
                        "out_dir": {"type": "string", "default": "/tmp/anse"}
                    }
                },
                description="Capture an RGB frame from camera",
                sensitivity="medium",
                cost_hint={"latency_ms": 200, "expensive": False}
            )
            
            self.tools.register(
                name="list_cameras",
                func=list_cameras,
                schema={"type": "object", "properties": {}},
                description="List available camera devices",
                sensitivity="low",
                cost_hint={"latency_ms": 100, "expensive": False}
            )
            
            self.tools.register(
                name="record_audio",
                func=record_audio,
                schema={
                    "type": "object",
                    "properties": {
                        "duration": {"type": "number", "default": 2.0, "minimum": 0.1, "maximum": 60},
                        "samplerate": {"type": "integer", "default": 16000},
                        "channels": {"type": "integer", "default": 1},
                        "out_dir": {"type": "string", "default": "/tmp/anse"}
                    }
                },
                description="Record audio from microphone",
                sensitivity="medium",
                cost_hint={"latency_ms": 2000, "expensive": False}
            )
            
            self.tools.register(
                name="list_audio_devices",
                func=list_audio_devices,
                schema={"type": "object", "properties": {}},
                description="List available audio input devices",
                sensitivity="low",
                cost_hint={"latency_ms": 50, "expensive": False}
            )
        
        # TTS tools (same for both modes)
        self.tools.register(
            name="say",
            func=say,
            schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "rate": {"type": "integer", "default": 200},
                    "volume": {"type": "number", "default": 1.0, "minimum": 0.0, "maximum": 1.0}
                },
                "required": ["text"]
            },
            description="Speak text using text-to-speech",
            sensitivity="low",
            cost_hint={"latency_ms": 500, "expensive": False}
        )
        
        self.tools.register(
            name="get_voices",
            func=get_voices,
            schema={"type": "object", "properties": {}},
            description="List available TTS voices",
            sensitivity="low",
            cost_hint={"latency_ms": 100, "expensive": False}
        )
        
        logger.info(f"Registered {len(self.tools.list_tools())} tools")

    def _load_plugins(self) -> None:
        """Load and register plugins from the plugins/ directory."""
        self.plugins: dict = {}
        try:
            plugin_loader = PluginLoader(plugin_dir="plugins")
            plugins = plugin_loader.load_all()

            if plugins:
                logger.info(f"Found {len(plugins)} plugin(s), registering...")
                plugin_loader.register_with_engine(self)

                for plugin_name, info in plugins.items():
                    logger.info(f"✓ Loaded plugin: {plugin_name} ({info['type']})")

                # Expose instances so callers (demos, other subsystems) can
                # reach a plugin's own methods, not just its registered tools.
                self.plugins = dict(plugin_loader.plugin_instances)

                # Any plugin implementing process_world_model_event() is a
                # reflex-style listener — subscribe it to the world model so
                # it reacts to events live instead of needing to be polled.
                # This is the actual wiring that makes the reflex system a
                # real event bus consumer rather than dead code that only
                # runs if something happens to call it directly.
                for plugin_name, instance in plugin_loader.plugin_instances.items():
                    if hasattr(instance, "process_world_model_event"):
                        self.world.subscribe(
                            lambda event, _inst=instance: _inst.process_world_model_event(event, self)
                        )
                        logger.info(f"✓ Subscribed {plugin_name} to world model events")
            else:
                logger.debug("No plugins found in plugins/ directory")

        except Exception as e:
            logger.warning(f"Failed to load plugins: {e}")
            # Don't crash if plugins fail to load - core engine should still work

    def _configure_rate_limits(self) -> None:
        """Configure rate limits from safety policy."""
        rate_limits = self.permissions.policy.get("rate_limits", {})
        
        for tool_name, limit in rate_limits.items():
            if self.tools.has_tool(tool_name):
                self.scheduler.set_rate_limit(tool_name, limit)
                logger.info(f"Set rate limit for {tool_name}: {limit} calls/min")
    
    def register_tool(self, name: str, func, description: str = "", 
                     parameters: dict = None, sensitivity: str = "low", 
                     cost_hint: dict = None) -> None:
        """Register a tool with the engine (used by plugin loader).
        
        Args:
            name: Tool name
            func: Async callable function
            description: Tool description
            parameters: Parameter schema
            sensitivity: "low", "medium", or "high"
            cost_hint: Cost hints for tool execution
        """
        if parameters is None:
            parameters = {}
        if cost_hint is None:
            cost_hint = {"latency_ms": 100}
        
        self.tools.register(
            name=name,
            func=func,
            schema={"type": "object", "properties": parameters},
            description=description,
            sensitivity=sensitivity,
            cost_hint=cost_hint
        )

    async def run(self, host: str = '127.0.0.1', port: int = 8765) -> None:
        """
        Start the engine and serve the agent bridge.
        
        Args:
            host: Host to bind to
            port: Port to bind to
        """
        logger.info(f"Starting ANSE engine on {host}:{port}")
        await self.bridge.serve(host, port)

    def get_stats(self) -> dict:
        """Get engine statistics."""
        world_stats = self.world.get_stats()
        return {
            "tools": list(self.tools.list_tools().keys()),
            "events": world_stats.get("total_events", 0),
            "scheduler": self.scheduler.get_stats(),
        }


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="ANSE - Autonomous Agent Control System")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind to")
    parser.add_argument("--policy", help="Path to safety policy YAML")
    
    args = parser.parse_args()
    
    core = EngineCore(policy_path=args.policy)
    
    try:
        asyncio.run(core.run(host=args.host, port=args.port))
    except KeyboardInterrupt:
        logger.info("Shutting down ANSE engine")


if __name__ == "__main__":
    main()
