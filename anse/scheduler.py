"""
Scheduler - Manages deterministic execution of tool calls.
"""
import asyncio
import time
from typing import Dict, Any, Optional
from anse.tool_registry import ToolRegistry
from anse.world_model import WorldModel
from anse.safety.permission import PermissionManager


class Scheduler:
    """
    Handles scheduling and execution of tool calls with rate limiting,
    timeouts, permission/approval enforcement, and event logging.

    This is the agent-facing call path (reached via AgentBridge). Reflexes
    call ToolRegistry directly and bypass this gate entirely — that's
    intentional, not an oversight: the reflex path has to stay sub-second
    and unconditional, so permission checks only apply to the deliberate
    (agent-initiated) path.
    """

    def __init__(
        self,
        tools: ToolRegistry,
        world: WorldModel,
        permissions: Optional[PermissionManager] = None,
    ):
        self.tools = tools
        self.world = world
        self.permissions = permissions
        self._call_counter = 0
        self._rate_limits: Dict[str, Dict[str, Any]] = {}

    def set_rate_limit(self, tool_name: str, calls_per_minute: int) -> None:
        """
        Set rate limit for a specific tool.

        Args:
            tool_name: Name of the tool
            calls_per_minute: Maximum calls allowed per minute
        """
        self._rate_limits[tool_name] = {
            "limit": calls_per_minute,
            "window": 60.0,
            "calls": [],
        }

    def _check_rate_limit(self, tool_name: str) -> bool:
        """
        Check if a tool call would exceed rate limits.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if call is allowed, False if rate limited
        """
        if tool_name not in self._rate_limits:
            return True

        limit_info = self._rate_limits[tool_name]
        now = time.time()
        window_start = now - limit_info["window"]

        # Remove old calls outside the window
        limit_info["calls"] = [t for t in limit_info["calls"] if t > window_start]

        # Check if we're at the limit
        if len(limit_info["calls"]) >= limit_info["limit"]:
            return False

        return True

    def _record_call(self, tool_name: str) -> None:
        """Record a tool call for rate limiting."""
        if tool_name in self._rate_limits:
            self._rate_limits[tool_name]["calls"].append(time.time())

    async def execute_call(
        self,
        agent_id: str,
        call_id: str,
        tool: str,
        args: Dict[str, Any],
        timeout: Optional[float] = 30.0,
    ) -> Dict[str, Any]:
        """
        Execute a tool call with rate limiting and timeout.

        Args:
            agent_id: Identifier of the calling agent
            call_id: Unique call identifier
            tool: Tool name
            args: Tool arguments
            timeout: Maximum execution time in seconds

        Returns:
            Result dictionary with status and data
        """
        self._call_counter += 1

        # Log the call attempt
        self.world.append_event(
            {
                "type": "tool_call",
                "agent_id": agent_id,
                "call_id": call_id,
                "tool": tool,
                "args": args,
            }
        )

        # Check permission scope and approval requirements
        if self.permissions is not None:
            allowed, reason = self.permissions.check_permission(
                agent_id, tool, required_scope=tool
            )
            if not allowed:
                result = {"status": "error", "error": "permission_denied", "reason": reason, "call_id": call_id}
                self.world.append_event(
                    {
                        "type": "tool_result",
                        "agent_id": agent_id,
                        "call_id": call_id,
                        "result": result,
                    }
                )
                return result

            if self.permissions.requires_approval(tool, scope=tool):
                result = {
                    "status": "error",
                    "error": "approval_required",
                    "reason": f"'{tool}' requires human approval before execution",
                    "call_id": call_id,
                }
                self.world.append_event(
                    {
                        "type": "tool_result",
                        "agent_id": agent_id,
                        "call_id": call_id,
                        "result": result,
                    }
                )
                return result

        # Check rate limits
        if not self._check_rate_limit(tool):
            result = {"status": "error", "error": "rate_limited", "call_id": call_id}
            self.world.append_event(
                {
                    "type": "tool_result",
                    "agent_id": agent_id,
                    "call_id": call_id,
                    "result": result,
                }
            )
            return result

        try:
            # Execute with timeout
            if timeout:
                result_data = await asyncio.wait_for(self.tools.call(tool, args), timeout)
            else:
                result_data = await self.tools.call(tool, args)

            self._record_call(tool)

            result = {"status": "ok", "call_id": call_id, "result": result_data}

        except asyncio.TimeoutError:
            result = {"status": "error", "error": "timeout", "call_id": call_id}
        except KeyError as e:
            result = {"status": "error", "error": f"tool_not_found: {e}", "call_id": call_id}
        except Exception as e:
            result = {
                "status": "error",
                "error": f"{type(e).__name__}: {str(e)}",
                "call_id": call_id,
            }

        # Log the result
        self.world.append_event(
            {
                "type": "tool_result",
                "agent_id": agent_id,
                "call_id": call_id,
                "result": result,
            }
        )

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        return {
            "total_calls": self._call_counter,
            "rate_limits": {
                name: {
                    "limit": info["limit"],
                    "current_usage": len(info["calls"]),
                }
                for name, info in self._rate_limits.items()
            },
        }
