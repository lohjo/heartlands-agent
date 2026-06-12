"""HITL stage → confirm round-trip (ADR-4). Nothing executes until confirmed."""

import pytest

pytest.importorskip("google.adk")  # tools.py imports ADK's ToolContext

from soar_orchestrator import tools as T


class FakeToolContext:
    """Minimal stand-in: tools only ever touch tool_context.state (a dict)."""
    def __init__(self, state=None):
        self.state = state or {}


def _ctx():
    return FakeToolContext({'tenant_config': {'tenant_id': 't_hitl', 'shop_name': 'Lim'}})


def test_stage_then_execute_marks_done():
    ctx = _ctx()
    staged = T.stage_send_whatsapp('Promo today!', audience='regulars', tool_context=ctx)
    assert staged['status'] == 'staged'
    aid = staged['action_id']
    assert staged['render_command']['layer'] == 'confirmation'
    assert ctx.state['staged_actions'][aid]['status'] == 'awaiting_confirmation'

    done = T.execute_staged_action(aid, tool_context=ctx)
    assert done['status'] == 'success'
    assert done['render_command']['action'] == 'executed'
    assert ctx.state['staged_actions'][aid]['status'] == 'executed'


def test_cannot_execute_unknown_action():
    ctx = _ctx()
    res = T.execute_staged_action('act_nope', tool_context=ctx)
    assert res['status'] == 'error'


def test_cancel_removes_staged_action():
    ctx = _ctx()
    aid = T.stage_google_business_update('hours', '7am-9pm', tool_context=ctx)['action_id']
    res = T.cancel_staged_action(aid, tool_context=ctx)
    assert res['status'] == 'success'
    assert aid not in ctx.state.get('staged_actions', {})


def test_missing_inventory_is_needs_info_not_error():
    ctx = _ctx()
    res = T.check_inventory('rice', tool_context=ctx)
    # No inventory known yet → gentle nudge, never a crash or a made-up number.
    assert res['status'] == 'needs_info'
    assert 'remember' in res['message'].lower()
