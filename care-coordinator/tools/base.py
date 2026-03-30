"""
Base interface for all Care Coordinator tools.

Every tool must subclass BaseTool, declare name/description/schema as
class-level attributes, and implement execute().
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Abstract base class for all tools in the Care Coordinator."""

    # ------------------------------------------------------------------ #
    # Subclasses MUST declare these                                        #
    # ------------------------------------------------------------------ #

    #: Unique tool name used as the function name in LLM tool calls.
    name: str = ""

    #: Human-readable description sent to the LLM as part of the schema.
    description: str = ""

    #: JSON Schema for the tool's input parameters.
    schema: dict = {}

    # ------------------------------------------------------------------ #
    # Permission flags (checked by the executor before running)           #
    # ------------------------------------------------------------------ #

    #: When True, the executor will reject the call if the session has not
    #: yet confirmed a patient via verify_patient.
    requires_patient_verification: bool = False

    # ------------------------------------------------------------------ #
    # Execution                                                            #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def execute(self, args: dict, db: dict, session: dict) -> Any:
        """Run the tool and return a JSON-serialisable result (dict or list).

        Args:
            args:    Validated input parameters from the LLM.
            db:      In-memory database (patients, providers, slots, …).
            session: Current workflow session dict.

        Returns:
            A dict or list that will be JSON-serialised and returned to the LLM.
        """
        ...
