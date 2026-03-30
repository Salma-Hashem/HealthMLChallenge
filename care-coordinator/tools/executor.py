"""
Tool executor for the Care Coordinator.

Single entry point for all tool calls. Responsibilities:
  1. Look up the tool in the registry.
  2. Enforce permission flags (e.g. requires_patient_verification).
  3. Validate inputs against the tool's JSON schema.
  4. Delegate to tool.execute(), timing the call.
  5. Serialise the result to a JSON string returned to the LLM.
  6. Log every execution (tool name, duration, success/failure).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from tools.registry import ToolRegistry, registry as _default_registry

logger = logging.getLogger(__name__)

# Map JSON Schema primitive types → Python types for fast validation.
_TYPE_MAP: dict[str, type | tuple] = {
    "string":  str,
    "integer": int,
    "number":  (int, float),
    "boolean": bool,
    "array":   list,
    "object":  dict,
}


class ToolExecutor:
    """Executes tools with input validation, permission checks, and logging."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def run(self, name: str, args: dict, db: dict, session: dict) -> str:
        """Execute a tool by name and return the result as a JSON string.

        This is the ONLY way tools should be called — never call tool.execute()
        directly from outside this module.
        """
        tool = self._registry.get_tool(name)
        if tool is None:
            logger.warning("Unknown tool requested: '%s'", name)
            return json.dumps({"error": f"Unknown tool: '{name}'"})

        # 1. Permission check
        if tool.requires_patient_verification and not session.get("patient_confirmed"):
            return json.dumps({
                "error": "Patient identity must be verified before calling this tool. "
                         "Call verify_patient first."
            })

        # 2. Input validation
        validation_error = self._validate(tool, args)
        if validation_error:
            logger.warning("Tool '%s' rejected — %s", name, validation_error)
            return json.dumps({"error": f"Invalid input: {validation_error}"})

        # 3. Execute with timing + error capture
        start = time.monotonic()
        try:
            result = tool.execute(args, db, session)
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug("Tool '%s' succeeded in %.1f ms", name, elapsed_ms)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "Tool '%s' raised after %.1f ms: %s", name, elapsed_ms, exc,
                exc_info=True,
            )
            return json.dumps({"error": f"Tool execution failed: {exc}"})

        # 4. Serialise — wrap non-dict/non-list scalars so JSON always works
        if not isinstance(result, (dict, list)):
            result = {"data": result}
        return json.dumps(result)

    # ------------------------------------------------------------------ #
    # Input validation                                                     #
    # ------------------------------------------------------------------ #

    def _validate(self, tool: Any, args: dict):
        """Return an error message string, or None if inputs are valid."""
        schema = tool.schema
        properties: dict = schema.get("properties", {})
        required: list = schema.get("required", [])

        # Required fields
        for field in required:
            if field not in args or args[field] is None:
                return f"Missing required field: '{field}'"

        # Type and enum checks for present fields
        for field, value in args.items():
            spec = properties.get(field)
            if spec is None:
                continue  # unknown extra fields are tolerated

            # Type check
            expected = spec.get("type")
            if expected and expected in _TYPE_MAP:
                # Special case: LLMs sometimes send integer IDs as floats
                if expected == "integer" and isinstance(value, float) and value.is_integer():
                    args[field] = int(value)
                elif not isinstance(value, _TYPE_MAP[expected]):
                    return (
                        f"Field '{field}' expects type '{expected}', "
                        f"got '{type(value).__name__}'"
                    )

            # Enum check
            allowed = spec.get("enum")
            if allowed and value not in allowed:
                return f"Field '{field}' must be one of {allowed}, got '{value}'"

        return None


# Module-level singleton wired to the default registry.
executor = ToolExecutor(_default_registry)
