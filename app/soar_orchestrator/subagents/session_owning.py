"""
Session-owning sub-agents — Heartland Copilot (ADR-1)
=====================================================
These follow the soar-main Screen_Advisor pattern VERBATIM in spirit: once
active they STAY active and keep handling the merchant's turns until an explicit
exit phrase, then transfer back to the root Heartland_Copilot. They own the
session for a focused, multi-step job.

  Onboarding_Agent — a deliberate "learn my business" session (ADR-7).
  Training_Agent   — a HECS micro-lesson (ADR-9, placeholder content).
  Quote_Agent      — a multi-step supplier quote (phase-2 workflow, ADR-10).

Built by factory functions (not module singletons) so build_agent(tenant_config)
can construct a fresh, per-tenant tree on the correct model (ADR-3).
"""

from google.adk.agents import LlmAgent

from soar_orchestrator import tools as T


_EXIT = (
    'Stay active and keep handling EVERY turn yourself. Transfer back to '
    'Heartland_Copilot ONLY when the merchant clearly signals they are done — '
    '"ok done", "that\'s all", "enough already", "ok can already", "go back". '
    'Until then, do not hand control back between turns.'
)


def build_onboarding_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name='Onboarding_Agent',
        model=model,
        description=(
            'Runs a focused listening session to learn the merchant\'s business. '
            'Route here for "help me set up", "learn about my shop", or the first '
            'structured onboarding session.'
        ),
        instruction=(
            'You are the Onboarding specialist for the Heartland Copilot. Your job '
            'is to learn this merchant\'s business through warm conversation and '
            'remember it — there is NO form.\n\n'
            'WORKFLOW:\n'
            '1. Chat naturally. Ask one easy thing at a time: what they sell, the '
            'shop name, who their main suppliers are, busiest days.\n'
            '2. EVERY time you learn something durable, call '
            'remember_business_fact(field, value) immediately — shop_name, '
            'shop_type, product_categories, <x>_supplier, opening_hours, '
            'inventory.<category>.\n'
            '3. Do not rush and do not interrogate. If they wander, follow.\n\n'
            + _EXIT + '\n'
            'Speak Singlish, short turns. Never invent — only remember what they '
            'actually say.'
        ),
        tools=[T.remember_business_fact, T.check_inventory, T.show_workflow_status],
    )


def build_training_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name='Training_Agent',
        model=model,
        description=(
            'Delivers a short in-store micro-lesson (HECS). Route here for '
            '"teach me how to...", "show me how to work with volunteers", or a '
            'how-to the merchant asks to be walked through.'
        ),
        instruction=(
            'You are the Training specialist (HECS micro-sessions, ADR-9). Deliver '
            'ONE short, practical lesson contextually — not a course.\n\n'
            'WORKFLOW:\n'
            '1. Use answer_grant_query or get_photo_tip to surface the relevant '
            'placeholder content, and teach it in plain Singlish, step by step.\n'
            '2. Keep each spoken step short; pause for the merchant.\n'
            '3. HECS partnership content is pending — say plainly when something '
            'is placeholder guidance to confirm later. Never invent specifics.\n\n'
            + _EXIT
        ),
        tools=[T.answer_grant_query, T.get_photo_tip, T.show_workflow_status],
    )


def build_quote_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name='Quote_Agent',
        model=model,
        description=(
            'Prepares a supplier quote request step by step. Route here for '
            '"get me a quote", "ask my supplier for price", "order from supplier".'
        ),
        instruction=(
            'You are the Supplier Quote specialist (phase-2 workflow, ADR-10).\n\n'
            'WORKFLOW:\n'
            '1. Find out which supplier and exactly what items/quantities.\n'
            '2. Call stage_supplier_quote(supplier, items) to stage it — this '
            'shows a confirmation card. Read it back.\n'
            '3. When the merchant confirms by voice, call '
            'execute_staged_action(action_id). If they decline, '
            'cancel_staged_action(action_id).\n'
            '4. If you don\'t know the supplier, ask and remember it with '
            'remember_business_fact.\n\n'
            + _EXIT
        ),
        tools=[
            T.stage_supplier_quote, T.execute_staged_action, T.cancel_staged_action,
            T.remember_business_fact, T.show_workflow_status,
        ],
    )
