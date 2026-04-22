"""
Central tool registry for the Care Coordinator.

All tools self-register on import by calling registry.register(ToolClass()).
The registry exposes the tool list in OpenAI function-calling format for the LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.base import BaseTool


class ToolRegistry:
    """Thread-safe (read-heavy) registry mapping tool names to BaseTool instances."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance.

        Raises:
            ValueError: If a tool with the same name has already been registered.
        """
        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                "Check for duplicate registrations or module re-imports."
            )
        if not tool.name:
            raise ValueError("Tool must have a non-empty name.")
        self._tools[tool.name] = tool

    # ------------------------------------------------------------------ #
    # Lookup                                                               #
    # ------------------------------------------------------------------ #

    def get_tool(self, name: str):
        """Return the tool registered under *name*, or None."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools in registration order."""
        return list(self._tools.values())

    # ------------------------------------------------------------------ #
    # LLM schema export                                                    #
    # ------------------------------------------------------------------ #

    def get_openai_tools(self) -> list[dict]:
        """Return all tools in OpenAI function-calling format (Cerebras compatible)."""
        result = []
        for tool in self._tools.values():
            schema = dict(tool.schema)
            # OpenAI treats a missing 'required' key as "no required fields"
            if "required" in schema and not schema["required"]:
                del schema["required"]
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                },
            })
        return result


# Module-level singleton — import this everywhere instead of instantiating locally.
registry = ToolRegistry()
