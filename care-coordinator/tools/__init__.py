"""
Care Coordinator tool registry — public interface.

Importing this package triggers auto-discovery: every domain sub-package
is imported, causing each tool module to call registry.register() and add
itself to the singleton registry.

Usage in orchestrator:
    from tools import registry, executor
    openai_tools = registry.get_openai_tools()
    result_str   = executor.run(tool_name, args, db, session)
"""

from tools.registry import registry  # noqa: F401
from tools.executor import executor  # noqa: F401

# ---------------------------------------------------------------------------
# Auto-discovery: import domain packages so tools self-register.
# Add new domain packages here as the tool suite grows.
# ---------------------------------------------------------------------------
import tools.patient       # registers: verify_patient, lookup_provider_info
import tools.scheduling    # registers: get_booking_history, find_available_slots,
                           #            list_alternative_providers,
                           #            check_provider_availability, book_appointment
import tools.insurance     # registers: verify_insurance, get_selfpay_rate
