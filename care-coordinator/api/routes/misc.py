"""
Miscellaneous routes: health checks, feedback, and frontend SPA serving.
"""

import json
import os
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, send_from_directory

misc_bp = Blueprint("misc", __name__)

# Path to compiled React SPA assets.
_FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist"
)


@misc_bp.route("/api/health", methods=["GET"])
def api_health():
    """Health check endpoint used by Docker and load balancers."""
    api_key_set = bool(os.environ.get("CEREBRAS_API_KEY"))
    if not api_key_set:
        return jsonify({
            "status": "degraded",
            "reason": "CEREBRAS_API_KEY is not set — chat endpoint will not function. "
                      "Set it in your .env file (see .env.example).",
        }), 503
    db = current_app.config["db"]
    return jsonify({
        "status": "ok",
        "service": "Care Coordinator Assistant",
        "llm": "cerebras/qwen-3-235b",
        "patients": len(db.get("patients", {})),
        "providers": len(db.get("providers", {})),
    })


@misc_bp.route("/api/feedback", methods=["POST"])
def submit_feedback():
    """Record thumbs-up/down feedback for a specific assistant message.

    Appends one JSON line to logs/feedback.jsonl (POC storage).
    No patient data — session_id and message_index only.
    """
    data = request.get_json() or {}
    session_id = data.get("session_id")
    message_index = data.get("message_index")
    feedback_val = data.get("feedback")          # "positive" | "negative" | null
    workflow_state = data.get("workflow_state", "")
    tool_calls = data.get("tool_calls_in_turn", [])
    # Truncate response preview to 500 chars; never store full patient data
    response_preview = (data.get("response_text") or "")[:500]

    if feedback_val not in ("positive", "negative", None):
        return jsonify({"error": "feedback must be 'positive', 'negative', or null"}), 400

    entry = {
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "session_id":         session_id,
        "message_index":      message_index,
        "feedback":           feedback_val,
        "workflow_state":     workflow_state,
        "tool_calls_in_turn": tool_calls,
        "response_preview":   response_preview,
    }

    # Write to logs/ directory at the project root.
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    feedback_path = os.path.join(logs_dir, "feedback.jsonl")
    with open(feedback_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    return jsonify({"success": True})


@misc_bp.route("/", defaults={"path": ""})
@misc_bp.route("/<path:path>")
def serve_frontend(path):
    """Serve the React SPA. API routes registered before this catch-all take priority."""
    frontend_dist = os.path.abspath(_FRONTEND_DIST)
    if path and os.path.exists(os.path.join(frontend_dist, path)):
        return send_from_directory(frontend_dist, path)
    return send_from_directory(frontend_dist, "index.html")
