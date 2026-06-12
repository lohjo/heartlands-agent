"""ADR-5: render_command enforced for _DISPLAY_TOOLS only, and every display
tool emits a valid layer."""

import pytest

pytest.importorskip("google.adk")

from soar_orchestrator import tools as T
from soar_orchestrator.agent import _DISPLAY_TOOLS, _VALID_LAYERS


class FakeToolContext:
    def __init__(self, state=None):
        self.state = state or {}


def _ctx():
    return FakeToolContext({'tenant_config': {
        'tenant_id': 't_r', 'shop_name': 'Lim', 'inventory': {'rice': '12 bags'},
    }})


def test_display_tools_emit_valid_layers():
    ctx = _ctx()
    samples = {
        'check_inventory': lambda: T.check_inventory('rice', tool_context=ctx),
        'draft_whatsapp_promo': lambda: T.draft_whatsapp_promo('Hi!', 'today', tool_context=ctx),
        'answer_grant_query': lambda: T.answer_grant_query('cdc_voucher', tool_context=ctx),
        'get_photo_tip': lambda: T.get_photo_tip('food', tool_context=ctx),
        'show_workflow_status': lambda: T.show_workflow_status(tool_context=ctx),
    }
    for name, call in samples.items():
        assert name in _DISPLAY_TOOLS
        cmd = call().get('render_command')
        assert cmd and cmd['layer'] in _VALID_LAYERS, name


def test_voice_only_tool_not_in_display_set():
    # remember_business_fact paints no panel — it must NOT require a render.
    assert 'remember_business_fact' not in _DISPLAY_TOOLS
    ctx = _ctx()
    res = T.remember_business_fact('opening_hours', '7am-9pm', tool_context=ctx)
    assert res['status'] == 'success'
    assert 'render_command' not in res


def test_five_canonical_layers_present():
    assert _VALID_LAYERS == {
        'document', 'inventory', 'workflow', 'knowledge', 'confirmation',
    }
