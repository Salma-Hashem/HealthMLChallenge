"""
Tests for agent-layer logic that runs without hitting a live LLM.

Covers:
  - guard_booking node (confirmation keyword detection, blocking, passthrough)
  - _is_rate_limit helper (429 detection)
  - _pop_last_ai_turn (regenerate: strips last AI turn from checkpoint)
"""

import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import _is_rate_limit, make_graph
from agent.orchestrator import _pop_last_ai_turn
from main import db


# ---------------------------------------------------------------------------
# _is_rate_limit
# ---------------------------------------------------------------------------

class TestIsRateLimit(unittest.TestCase):

    def test_detects_429_in_message(self):
        assert _is_rate_limit(Exception("HTTP 429 Too Many Requests"))

    def test_detects_too_many_requests(self):
        assert _is_rate_limit(Exception("too_many_requests from provider"))

    def test_detects_queue_exceeded(self):
        assert _is_rate_limit(Exception("queue_exceeded: retry later"))

    def test_ignores_unrelated_errors(self):
        assert not _is_rate_limit(Exception("Connection timeout"))

    def test_ignores_500_error(self):
        assert not _is_rate_limit(Exception("500 Internal Server Error"))


# ---------------------------------------------------------------------------
# guard_booking — invoked via the compiled graph node
# ---------------------------------------------------------------------------

def _make_ai_msg_with_tool_call(tool_name: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": "tc_001", "name": tool_name, "args": {}}],
    )


def _run_guard(workflow_state: str, human_text: str, tool_name: str = "book_appointment") -> dict:
    """Invoke the guard_booking node directly through the compiled graph."""
    graph = make_graph(db)
    state = {
        "workflow_state": workflow_state,
        "messages": [
            HumanMessage(content=human_text),
            _make_ai_msg_with_tool_call(tool_name),
        ],
        "patient_id": None,
        "patient_confirmed": False,
        "referrals": [],
        "active_referral_index": 0,
        "completed_bookings": [],
        "tool_call_count": 0,
        "last_booking_confirmation": None,
    }
    return graph.nodes["guard_booking"].invoke(state)


class TestGuardBooking(unittest.TestCase):

    # --- Not in confirm_booking — guard is a no-op -------------------------

    def test_passthrough_when_not_confirm_booking(self):
        result = _run_guard("check_availability", "yes please")
        # No blocking messages added, workflow_state unchanged
        assert not any(isinstance(m, ToolMessage) for m in result.get("messages", []))
        assert result.get("workflow_state") != "execute_booking"

    def test_passthrough_when_execute_booking(self):
        result = _run_guard("execute_booking", "yes")
        assert not any(isinstance(m, ToolMessage) for m in result.get("messages", []))

    # --- In confirm_booking, nurse confirms --------------------------------

    def test_yes_advances_to_execute_booking(self):
        result = _run_guard("confirm_booking", "yes")
        assert result.get("workflow_state") == "execute_booking"

    def test_confirm_keyword_advances(self):
        result = _run_guard("confirm_booking", "please confirm")
        assert result.get("workflow_state") == "execute_booking"

    def test_book_it_advances(self):
        result = _run_guard("confirm_booking", "book it")
        assert result.get("workflow_state") == "execute_booking"

    def test_go_ahead_advances(self):
        result = _run_guard("confirm_booking", "go ahead")
        assert result.get("workflow_state") == "execute_booking"

    # --- In confirm_booking, nurse has NOT confirmed -----------------------

    def test_blocks_book_appointment_without_confirmation(self):
        result = _run_guard("confirm_booking", "what time is it?")
        tool_msgs = [m for m in result.get("messages", []) if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].name == "book_appointment"
        payload = json.loads(tool_msgs[0].content)
        assert "confirmation" in payload["error"].lower()

    def test_blocks_other_tools_while_confirm_pending(self):
        result = _run_guard("confirm_booking", "what time is it?", tool_name="verify_insurance")
        tool_msgs = [m for m in result.get("messages", []) if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].name == "verify_insurance"
        payload = json.loads(tool_msgs[0].content)
        assert "blocked" in payload["error"].lower()

    def test_each_tool_call_gets_an_error_message(self):
        """All pending tool calls must receive a ToolMessage — no orphaned calls."""
        graph = make_graph(db)
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc_001", "name": "book_appointment", "args": {}},
                {"id": "tc_002", "name": "verify_insurance", "args": {}},
            ],
        )
        state = {
            "workflow_state": "confirm_booking",
            "messages": [HumanMessage(content="maybe later"), ai_msg],
            "patient_id": None,
            "patient_confirmed": False,
            "referrals": [],
            "active_referral_index": 0,
            "completed_bookings": [],
            "tool_call_count": 0,
            "last_booking_confirmation": None,
        }
        result = graph.nodes["guard_booking"].invoke(state)
        tool_msgs = [m for m in result.get("messages", []) if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        ids = {m.tool_call_id for m in tool_msgs}
        assert ids == {"tc_001", "tc_002"}


# ---------------------------------------------------------------------------
# _pop_last_ai_turn
# ---------------------------------------------------------------------------

class TestPopLastAiTurn(unittest.TestCase):

    def _make_graph_with_state(self, messages: list) -> tuple:
        graph = make_graph(db)
        config = {"configurable": {"thread_id": f"test-pop-{id(messages)}"}}
        graph.update_state(config, {
            "messages": messages,
            "patient_id": None,
            "patient_confirmed": False,
            "workflow_state": "greet",
            "referrals": [],
            "active_referral_index": 0,
            "completed_bookings": [],
            "tool_call_count": 0,
            "last_booking_confirmation": None,
        })
        return graph, config

    def _get_messages(self, graph, config) -> list:
        snap = graph.get_state(config)
        return list(snap.values.get("messages", []))

    def test_removes_trailing_plain_ai_message(self):
        msgs = [
            HumanMessage(content="hello"),
            AIMessage(content="How can I help?"),
        ]
        graph, config = self._make_graph_with_state(msgs)
        _pop_last_ai_turn(graph, config)
        remaining = self._get_messages(graph, config)
        assert len(remaining) == 1
        assert isinstance(remaining[-1], HumanMessage)

    def test_removes_ai_plus_tool_messages(self):
        ai_with_tools = AIMessage(
            content="",
            tool_calls=[{"id": "tc_1", "name": "verify_patient", "args": {}}],
        )
        msgs = [
            HumanMessage(content="Book for John"),
            ai_with_tools,
            ToolMessage(content='{"found": true}', tool_call_id="tc_1", name="verify_patient"),
        ]
        graph, config = self._make_graph_with_state(msgs)
        _pop_last_ai_turn(graph, config)
        remaining = self._get_messages(graph, config)
        assert len(remaining) == 1
        assert isinstance(remaining[-1], HumanMessage)

    def test_does_not_remove_human_messages(self):
        msgs = [HumanMessage(content="hello")]
        graph, config = self._make_graph_with_state(msgs)
        _pop_last_ai_turn(graph, config)
        remaining = self._get_messages(graph, config)
        assert len(remaining) == 1

    def test_is_nonfatal_on_empty_state(self):
        graph = make_graph(db)
        config = {"configurable": {"thread_id": "test-empty-state"}}
        _pop_last_ai_turn(graph, config)  # must not raise


if __name__ == "__main__":
    unittest.main()
