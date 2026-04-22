"""
Chat endpoint — routes user messages through the LLM agent pipeline.
"""

from flask import Blueprint, current_app, jsonify, request

from agent.orchestrator import handle_message

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/api/chat", methods=["POST"])
def chat():
    db = current_app.config["db"]

    data = request.get_json() or {}
    session_id = data.get("session_id") or None
    message = (data.get("message") or "").strip()
    regenerate = bool(data.get("regenerate", False))

    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400

    try:
        result = handle_message(session_id, message, db, regenerate=regenerate)
        return jsonify(result)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {str(exc)}"}), 500
