"""
Ephemeral sub-agents — Heartland Copilot (ADR-1)
================================================
These follow the soar-main Briefing_Agent pattern: execute ONE task, speak the
answer, and IMMEDIATELY transfer back to Heartland_Copilot. They never hold the
session.

  HECS_Lookup_Agent   — a quick grant / scheme / voucher fact.
  Supplier_Info_Agent — a quick "who is my X supplier" lookup.

Built by factories on the per-tenant model (ADR-3).
"""

from google.adk.agents import LlmAgent

from soar_orchestrator import tools as T


_HANDBACK = (
    'Do your ONE task, say the answer in one short Singlish sentence, then '
    'IMMEDIATELY transfer back to Heartland_Copilot. You do not handle anything '
    'else.'
)


def build_hecs_lookup_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name='HECS_Lookup_Agent',
        model=model,
        description=(
            'Quick lookup of a single grant, scheme, or voucher fact. Route here '
            'for "what is the CDC voucher", "is there a grant for X", quick '
            'one-shot scheme questions.'
        ),
        instruction=(
            'You are the HECS quick-lookup. Call answer_grant_query(topic) for the '
            'merchant\'s question, state the gist plainly (flag that details are '
            'placeholder and should be confirmed), then hand back.\n\n' + _HANDBACK
        ),
        tools=[T.answer_grant_query],
    )


def build_supplier_info_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name='Supplier_Info_Agent',
        model=model,
        description=(
            'Quick lookup of one of the merchant\'s own suppliers. Route here for '
            '"who is my rice supplier", "what\'s my chicken supplier called".'
        ),
        instruction=(
            'You are the supplier quick-lookup. The merchant\'s known suppliers are '
            'in their profile. If you know the supplier, say it. If you don\'t, say '
            '"I don\'t have your <x> supplier yet — tell me and I\'ll remember," and '
            'call remember_business_fact when they answer. Never invent a supplier '
            'name. Then hand back.\n\n' + _HANDBACK
        ),
        tools=[T.remember_business_fact],
    )
