"""
Entry point for the Care Coordinator Assistant.

Boots the application in this order:
  1. Load .env
  2. Parse data_sheet.txt → in-memory DB
  3. Generate appointment slots
  4. Build + register the LangGraph compiled graph
  5. Create the Flask app via the api factory
  6. Run the dev server (or expose `app` for gunicorn)

Gunicorn usage (production):
    gunicorn main:app --bind 0.0.0.0:5000 --workers 2 --timeout 120
"""

import os
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

from data.loader import load_all_data
from core.slots import generate_slots
from agent.graph import make_graph
import agent.orchestrator as _orchestrator
from api import create_app

# --- Load data ---
_DATA_SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "data_sheet.txt")
db = load_all_data(_DATA_SHEET)
db["slots"] = generate_slots(db["providers"], db["departments"], num_days=28)

# Build a provider→slots index for O(1) lookups in find_available_slots,
# list_alternative_providers, and the scheduling API endpoints.
_slots_by_provider: dict = defaultdict(list)
for _slot in db["slots"].values():
    _slots_by_provider[_slot.provider_id].append(_slot)
db["slots_by_provider"] = dict(_slots_by_provider)

# --- Wire the LangGraph graph ---
# Done post-DB-load so the graph factory can capture `db` by closure —
# provider/slot objects stay out of the MemorySaver checkpoint.
_orchestrator.set_graph(make_graph(db))

# --- Create Flask app ---
app = create_app(db)

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5000))
    app.run(debug=True, port=port)
