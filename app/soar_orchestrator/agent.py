"""
Heartland Copilot — Agent Topology (ADR-1 / ADR-3 / ADR-5)
==========================================================
Hub-and-spoke. The root Heartland_Copilot owns the direct merchant tools and
routes to two kinds of sub-agent:

  Heartland_Copilot (root)
    ├── direct tools (inventory, whatsapp draft, grants, photos, remember, HITL)
    └── sub_agents:
          session-owning (stay until exit phrase — Screen_Advisor pattern):
            ├── Onboarding_Agent
            ├── Training_Agent
            └── Quote_Agent
          ephemeral (execute → speak → transfer back — Briefing pattern):
            ├── HECS_Lookup_Agent
            └── Supplier_Info_Agent

ADR-3: agents are NOT module singletons. `build_agent(tenant_config)` builds a
fresh per-tenant tree, so the persona and remembered facts are baked into the
prompt at session start. main.py calls this per connection.

ADR-5: `render_command` is OPTIONAL, enforced SELECTIVELY via `_DISPLAY_TOOLS`.
Voice-only tools (remember_business_fact) paint no panel and need none. Adding a
NEW render layer is a 3-place change — see CLAUDE.md checklist.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.tools import BaseTool
from google.adk.tools.tool_context import ToolContext
from typing import Any, Dict, Optional

from . import tools as T
from .personas import root_instruction
from .subagents.session_owning import (
    build_onboarding_agent, build_training_agent, build_quote_agent,
)
from .subagents.ephemeral import (
    build_hecs_lookup_agent, build_supplier_info_agent,
)

# Native-audio Live model for real-time voice I/O (us-central1 — see README
# region strategy). Verify the current id at:
# https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models
MODEL_NATIVE: str = os.environ.get('DEMO_AGENT_MODEL', 'gemini-2.0-flash-live-001')

# Half-cascade flash for `adk web` routing tests (native audio rejects
# generateContent). ADK_WEB=1 → flash everywhere.
MODEL_FLASH: str = 'gemini-2.5-flash'
_adk_web = os.environ.get('ADK_WEB', '0').strip() == '1'
_root_model = MODEL_FLASH if _adk_web else MODEL_NATIVE
_sub_model = MODEL_FLASH if _adk_web else MODEL_NATIVE


# ---------------------------------------------------------------------------
# ADR-5 — render contract, enforced only for display tools
# ---------------------------------------------------------------------------
# Tools listed here MUST return a `render_command`; the after-tool callback
# rejects them if they don't. Tools NOT listed (e.g. remember_business_fact)
# are voice-only and need no render layer. To add a layer, update this set,
# the tool in tools.py, and the app.js dispatch — all three (see CLAUDE.md).
_DISPLAY_TOOLS = {
    'check_inventory',              # inventory
    'draft_whatsapp_promo',         # document
    'answer_grant_query',           # knowledge
    'get_photo_tip',                # knowledge
    'show_workflow_status',         # workflow
    'stage_send_whatsapp',          # confirmation
    'stage_google_business_update', # confirmation
    'stage_supplier_quote',         # confirmation
    'execute_staged_action',        # confirmation
    'cancel_staged_action',         # confirmation
}

_VALID_LAYERS = {'document', 'inventory', 'workflow', 'knowledge', 'confirmation'}


def _validate_after_tool(
    tool: BaseTool,
    args: Dict[str, Any],
    tool_context: ToolContext,
    tool_response: Dict,
) -> Optional[Dict]:
    """Enforce the render contract for display tools only (ADR-5)."""
    if not isinstance(tool_response, dict):
        return {'status': 'error', 'message': 'Tool returned a non-dict response.'}
    if tool.name not in _DISPLAY_TOOLS:
        return None  # voice-only tool — no render_command required
    # needs_info / error results are allowed to carry a fallback render or none.
    if tool_response.get('status') in ('error', 'needs_info'):
        return None
    cmd = tool_response.get('render_command')
    if not cmd:
        return {'status': 'error', 'message': f'{tool.name}: missing render_command.'}
    if cmd.get('layer') not in _VALID_LAYERS:
        return {'status': 'error',
                'message': f'{tool.name}: invalid render layer "{cmd.get("layer")}".'}
    return None


# Direct tools the root Copilot wields itself (multi-action + one-offs).
_ROOT_TOOLS = [
    T.check_inventory,
    T.draft_whatsapp_promo,
    T.answer_grant_query,
    T.get_photo_tip,
    T.show_workflow_status,
    T.remember_business_fact,
    T.stage_send_whatsapp,
    T.stage_google_business_update,
    T.stage_supplier_quote,
    T.execute_staged_action,
    T.cancel_staged_action,
]


def build_agent(tenant_config: dict) -> LlmAgent:
    """Construct a per-tenant Heartland_Copilot tree (ADR-3).

    The persona and known facts are folded into the root instruction at build
    time, so an incomplete tenant_config is handled gracefully via fallback
    language rather than errors (ADR-7).
    """
    tenant_config = tenant_config or {}

    sub_agents = [
        build_onboarding_agent(_sub_model),
        build_training_agent(_sub_model),
        build_quote_agent(_sub_model),
        build_hecs_lookup_agent(_sub_model),
        build_supplier_info_agent(_sub_model),
    ]

    return LlmAgent(
        name='Heartland_Copilot',
        model=_root_model,
        description=(
            'Voice-first business co-pilot for a Singapore heartland merchant. '
            'Handles direct merchant tasks and routes focused jobs to specialists.'
        ),
        instruction=root_instruction(tenant_config),
        sub_agents=sub_agents,
        tools=_ROOT_TOOLS,
        after_tool_callback=_validate_after_tool,
    )
