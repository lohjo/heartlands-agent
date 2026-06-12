"""
Heartland Copilot — Tool Functions
==================================
IMPORTANT: Docstrings in this file are INSTRUCTIONS TO GEMINI, not human docs.
They tell the model when and how to call each tool. Per ADR-5 every
merchant-facing tool docstring includes Singlish phrase examples as a
natural-language-to-parameter mapping — e.g. "how many bags of rice I still
got" -> check_inventory(category='rice'). Write them that way, always.

State (ADR-3): there are NO module-level mutable singletons here. Every piece
of per-merchant state lives in `tool_context.state`, which is hydrated from and
persisted to Firestore by FirestoreSessionService. `tenant_config` is seeded
into state by main.py at session start.

Return convention: every tool returns a dict with at least `status`. Tools that
paint a panel ALSO return a `render_command` (enforced for _DISPLAY_TOOLS only,
see agent.py / ADR-5):

    {
      'status': 'success' | 'error',
      'render_command': {
          'layer': 'document'|'inventory'|'workflow'|'knowledge'|'confirmation',
          'action': 'show' | 'hide' | ...,
          ...payload the matching app.js handler expects
      }
    }

Progressive trust (ADR-7): a missing tenant_config field NEVER errors and NEVER
hallucinates. Tools return a gentle 'needs_info' payload whose message tells the
merchant what to say so the Copilot can remember it for next time.
"""

import datetime
import logging
import uuid

from google.adk.tools.tool_context import ToolContext

from shared.tenant_config import field_or_fallback, remember_fact

logger = logging.getLogger('heartland.tools')


# ---------------------------------------------------------------------------
# State helpers — everything goes through tool_context.state (ADR-3)
# ---------------------------------------------------------------------------

def _config(tool_context: ToolContext) -> dict:
    """The merchant's tenant_config as seeded into session state by main.py."""
    if tool_context is None:
        return {}
    return tool_context.state.get('tenant_config', {}) or {}


def _tenant_id(tool_context: ToolContext) -> str:
    return _config(tool_context).get('tenant_id', 'unknown')


def _staged(tool_context: ToolContext) -> dict:
    """The staged-action registry for HITL (ADR-4), kept in session state."""
    if tool_context is None:
        return {}
    return tool_context.state.setdefault('staged_actions', {})


def _needs_info(prompt_to_merchant: str) -> dict:
    """Uniform 'I don't know that yet' result — fallback language, not an error."""
    return {
        'status': 'needs_info',
        'message': prompt_to_merchant,
        'render_command': {'layer': 'workflow', 'action': 'needs_info',
                           'message': prompt_to_merchant},
    }


# ===========================================================================
# v1 dead-time tasks (ADR-10 priority): inventory, WhatsApp, grants, photos
# ===========================================================================

def check_inventory(category: str, tool_context: ToolContext = None) -> dict:
    """Use when the merchant asks how much stock they have of something.

    `category` is the product, lowercased and singular: 'rice', 'oil', 'eggs',
    'sugar', 'milk_powder'.

    Singlish / Mandarin mappings:
      "how many bags of rice I still got"   -> category='rice'
      "rice left how many ah"               -> category='rice'
      "still got egg or not"                -> category='eggs'
      "我还有多少米"                          -> category='rice'

    If we have never been told this merchant's stock for that category, do NOT
    guess — the tool returns a needs_info result and you should say something
    like "I don't have your rice count yet — tell me and I'll remember."
    """
    category = (category or '').lower().strip().replace(' ', '_')
    inventory = (_config(tool_context).get('inventory') or {})
    if category not in inventory:
        return _needs_info(
            f"I don't have your {category or 'stock'} count yet. "
            f"Tell me how many you have and I'll remember it for next time."
        )
    qty = inventory[category]
    return {
        'status': 'success',
        'category': category,
        'quantity': qty,
        'render_command': {
            'layer': 'inventory', 'action': 'show',
            'category': category, 'quantity': qty,
            'all': inventory,
        },
    }


def draft_whatsapp_promo(message: str, occasion: str = '',
                        tool_context: ToolContext = None) -> dict:
    """Use to DISPLAY a WhatsApp promotion you have drafted for the merchant.

    YOU compose the promo text yourself (warm, Singlish, with the shop name and
    any details the merchant gave) and pass it as `message`. This tool only
    renders it as a card the merchant can read back — drafting is safe, so there
    is no confirmation here. Actually SENDING it is a separate, staged action
    (stage_send_whatsapp) because that is outward-facing.

    `occasion` is a short label: 'Hari Raya', 'weekend special', 'tomorrow'.

    Singlish mappings:
      "eh help me draft a whatsapp promo for tomorrow"
          -> occasion='tomorrow', message=<you write the promo>
      "write something for hari raya sale"
          -> occasion='Hari Raya', message=<you write the promo>
    """
    shop = field_or_fallback(_config(tool_context), 'shop_name', 'your shop')
    message = (message or '').strip()
    if not message:
        return _needs_info("Tell me what the promo is about and I'll draft it.")
    return {
        'status': 'success',
        'render_command': {
            'layer': 'document', 'action': 'show',
            'doc_type': 'whatsapp_promo',
            'title': f'WhatsApp promo · {occasion}'.strip(' ·'),
            'shop': shop,
            'body': message,
        },
    }


def answer_grant_query(topic: str, tool_context: ToolContext = None) -> dict:
    """Use when the merchant asks about a government scheme, grant, or voucher.

    `topic` is a short key: 'cdc_voucher', 'psg', 'edg', 'productivity_solutions',
    'sfec', 'general'.

    Singlish mappings:
      "cdc voucher how to claim ah"     -> topic='cdc_voucher'
      "got any grant for my shop?"      -> topic='general'
      "how to get the productivity grant"-> topic='psg'

    HECS content partnership is pending (ADR-9) — this returns PLACEHOLDER
    guidance for v1. State plainly that details should be confirmed, never
    invent figures or deadlines.
    """
    topic = (topic or 'general').lower().strip().replace(' ', '_')
    placeholder = {
        'cdc_voucher': ('CDC Vouchers', 'Residents claim CDC vouchers online and can spend '
                        'them at participating heartland shops. To accept them, register your '
                        'shop as a participating merchant. (Placeholder — confirm current '
                        'details with your CDC before relying on this.)'),
        'psg': ('Productivity Solutions Grant', 'PSG supports adoption of pre-approved digital '
                'solutions, typically co-funding part of the cost. Eligibility and rates change. '
                '(Placeholder — verify on the official scheme page.)'),
        'general': ('Support schemes', 'There are several heartland and SME schemes covering '
                    'digital tools, vouchers, and upgrading. Tell me what you want to do and '
                    "I'll point you to the closest one. (Placeholder content, v1.)"),
    }
    title, body = placeholder.get(topic, placeholder['general'])
    return {
        'status': 'success',
        'render_command': {
            'layer': 'knowledge', 'action': 'show',
            'topic': topic, 'title': title, 'body': body,
            'source': 'HECS placeholder (v1)',
        },
    }


def get_photo_tip(subject: str = 'product', tool_context: ToolContext = None) -> dict:
    """Use when the merchant asks how to take a better photo of their product.

    `subject`: 'food', 'product', 'shopfront', 'person'.

    Singlish mappings:
      "how to take nice photo of my kaya toast"  -> subject='food'
      "my product photo always look ugly leh"    -> subject='product'
      "how to photograph my shop front"          -> subject='shopfront'
    """
    subject = (subject or 'product').lower().strip()
    tips = {
        'food': ['Shoot near a window — soft daylight beats the ceiling light.',
                 'Get close and slightly above the plate at 45°.',
                 'Wipe the plate edge and add one prop (chopsticks, a drink).'],
        'product': ['Use a plain background — a clean wall or cloth.',
                    'Daylight, no flash. Flash flattens everything.',
                    'Fill the frame; hold the phone with both hands and tap to focus.'],
        'shopfront': ['Shoot in the morning when light is even.',
                      'Stand across the walkway so the whole signboard fits.',
                      'Keep verticals straight — line the signboard with the top edge.'],
    }
    chosen = tips.get(subject, tips['product'])
    return {
        'status': 'success',
        'render_command': {
            'layer': 'knowledge', 'action': 'show',
            'topic': f'photo_{subject}',
            'title': f'Photo tips · {subject}',
            'bullets': chosen,
            'source': 'Heartland Copilot tips',
        },
    }


def show_workflow_status(tool_context: ToolContext = None) -> dict:
    """Use when the merchant asks what's pending, in progress, or waiting on them.

    Singlish mappings:
      "what I still need to do ah"      -> show_workflow_status()
      "anything waiting for me?"        -> show_workflow_status()
      "what's pending"                  -> show_workflow_status()
    """
    staged = _staged(tool_context)
    items = [{
        'action_id': aid,
        'type': s.get('type'),
        'summary': s.get('preview', ''),
        'status': s.get('status', 'awaiting_confirmation'),
    } for aid, s in staged.items()]
    return {
        'status': 'success',
        'render_command': {'layer': 'workflow', 'action': 'show', 'items': items},
    }


# ===========================================================================
# Progressive trust (ADR-7): remember what the merchant tells us
# ===========================================================================

def remember_business_fact(field: str, value: str,
                          tool_context: ToolContext = None) -> dict:
    """Use whenever the merchant tells you something durable about their business
    that you did not already know — a supplier, the shop name, opening hours, a
    product category, their stock of something. This grows their profile so you
    don't have to ask again. This is voice-only: it paints no panel.

    `field` is a short snake_case key; `value` is what they said.

    Singlish mappings:
      "my rice supplier is Lim Huat"        -> field='rice_supplier', value='Lim Huat'
      "my shop called Lim Provision"        -> field='shop_name', value='Lim Provision'
      "I sell mostly vegetables and eggs"   -> field='product_categories', value='vegetables, eggs'
      "I still got 12 bags of rice"         -> field='inventory.rice', value='12 bags'
      "we open from 7am to 9pm"             -> field='opening_hours', value='7am-9pm'

    For an inventory count, use field='inventory.<category>'.
    """
    field = (field or '').strip()
    value = (value or '').strip()
    if not field or not value:
        return {'status': 'error', 'message': 'Need both a field and a value to remember.'}

    config = _config(tool_context)
    tenant_id = config.get('tenant_id', 'unknown')

    # inventory.<category> shorthand updates the inventory map in place.
    if field.startswith('inventory.'):
        category = field.split('.', 1)[1].lower().strip().replace(' ', '_')
        config.setdefault('inventory', {})[category] = value
        if tool_context is not None:
            tool_context.state['tenant_config'] = config
        from shared.tenant_config import save_tenant_config
        save_tenant_config(tenant_id, config)
        return {'status': 'success', 'remembered': {field: value}}

    updated = remember_fact(tenant_id, field, value)          # persists to Firestore
    if tool_context is not None:
        tool_context.state['tenant_config'] = updated          # keep session copy fresh
    return {'status': 'success', 'remembered': {field: value}}


# ===========================================================================
# HITL — stage → confirm (ADR-4). Voice is the confirmation channel.
# Every high-risk / outward-facing action is a tool PAIR:
#   stage_[action]()         -> staged preview + confirmation render card
#   execute_staged_action()  -> runs it after the merchant says "confirm"
# ===========================================================================

def _stage(tool_context: ToolContext, action_type: str, preview: str, params: dict) -> dict:
    action_id = f'act_{uuid.uuid4().hex[:8]}'
    _staged(tool_context)[action_id] = {
        'type': action_type, 'preview': preview, 'params': params,
        'status': 'awaiting_confirmation',
        'staged_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return {
        'status': 'staged',
        'action_id': action_id,
        'render_command': {
            'layer': 'confirmation', 'action': 'show',
            'action_id': action_id, 'action_type': action_type, 'preview': preview,
        },
    }


def stage_send_whatsapp(message: str, audience: str = 'all customers',
                       tool_context: ToolContext = None) -> dict:
    """Stage SENDING a WhatsApp promo (outward-facing → must be confirmed).

    Pass the final `message` and who it goes to. Returns a confirmation card;
    nothing is sent until the merchant says "confirm" and you call
    execute_staged_action(action_id).

    Singlish mappings:
      "ok send this to my customers"   -> stage_send_whatsapp(message=<the draft>, audience='all customers')
      "blast to the regulars"          -> stage_send_whatsapp(message=<the draft>, audience='regulars')
    """
    message = (message or '').strip()
    if not message:
        return _needs_info('Draft the message first, then I can send it.')
    preview = f'Send WhatsApp to {audience}:\n“{message}”'
    return _stage(tool_context, 'send_whatsapp', preview,
                 {'message': message, 'audience': audience})


def stage_google_business_update(field: str, value: str,
                                tool_context: ToolContext = None) -> dict:
    """Stage an update to the merchant's Google Business profile (outward-facing).

    `field`: 'hours', 'phone', 'description', 'address', 'photo'.

    Singlish mappings:
      "update my google opening hours to 7 to 9"
          -> stage_google_business_update(field='hours', value='7am-9pm')
      "change my google shop description"
          -> stage_google_business_update(field='description', value=<text>)
    """
    field = (field or '').lower().strip()
    value = (value or '').strip()
    if not field or not value:
        return _needs_info('Tell me which Google Business detail to change and the new value.')
    preview = f'Update Google Business {field} → “{value}”'
    return _stage(tool_context, 'google_business_update', preview,
                 {'field': field, 'value': value})


def stage_supplier_quote(supplier: str, items: str,
                        tool_context: ToolContext = None) -> dict:
    """Stage a quote request to a supplier (phase-2 workflow, ADR-10 — minimal v1).

    `supplier` is the supplier key or name; `items` is what to quote.

    Singlish mappings:
      "eh send quote to my chicken supplier"
          -> stage_supplier_quote(supplier='chicken', items=<ask what items>)
      "ask Lim Huat for price of 20 bags rice"
          -> stage_supplier_quote(supplier='Lim Huat', items='20 bags rice')
    """
    supplier = (supplier or '').strip()
    resolved = field_or_fallback(_config(tool_context), f'{supplier}_supplier', supplier)
    items = (items or '').strip()
    if not items:
        return _needs_info(f'What should I ask {resolved or "the supplier"} to quote for?')
    preview = f'Request quote from {resolved}:\n{items}'
    return _stage(tool_context, 'supplier_quote', preview,
                 {'supplier': resolved, 'items': items})


def execute_staged_action(action_id: str, tool_context: ToolContext = None) -> dict:
    """Use ONLY after the merchant has CONFIRMED a staged action by voice
    ("confirm", "yes send", "ok do it", "可以"). Executes the staged action and
    marks it done. If they decline ("no", "cancel", "never mind"), do NOT call
    this — call cancel_staged_action instead.

    `action_id` is the id returned by the matching stage_* tool.

    Singlish mappings (merchant CONFIRMS):
      "confirm" / "yes send it" / "ok do it lah" -> execute_staged_action(action_id=<id>)
    """
    staged = _staged(tool_context)
    action = staged.get(action_id)
    if not action:
        return {'status': 'error', 'message': 'No matching staged action to confirm.'}
    if action.get('status') == 'executed':
        return {'status': 'error', 'message': 'That action was already done.'}

    # v1: outward integrations (WhatsApp Business API, Google Business API) are
    # not wired yet — we record the execution so the workflow tracker and logs
    # reflect it. Real dispatch lands when those endpoints are approved.
    action['status'] = 'executed'
    action['executed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        'status': 'success',
        'action_id': action_id,
        'action_type': action['type'],
        'render_command': {
            'layer': 'confirmation', 'action': 'executed',
            'action_id': action_id, 'action_type': action['type'],
            'preview': action.get('preview', ''),
        },
    }


def cancel_staged_action(action_id: str, tool_context: ToolContext = None) -> dict:
    """Use when the merchant DECLINES a staged action ("no", "cancel", "don't send").

    Singlish mappings:
      "no don't send" / "cancel" / "never mind" -> cancel_staged_action(action_id=<id>)
    """
    staged = _staged(tool_context)
    action = staged.pop(action_id, None)
    if not action:
        return {'status': 'error', 'message': 'Nothing staged to cancel.'}
    return {
        'status': 'success', 'action_id': action_id,
        'render_command': {'layer': 'confirmation', 'action': 'cancelled',
                           'action_id': action_id},
    }
