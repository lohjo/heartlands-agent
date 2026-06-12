"""
Heartland Copilot orchestrator package.

Kept the module name `soar_orchestrator` deliberately: the deployment runbook
(README) hard-codes it in the "run uvicorn from inside app/" instruction, and
the ADK import path depends on it.

Exports the per-tenant agent factory (ADR-3) instead of a module-level
root_agent singleton.
"""

from .agent import build_agent

__all__ = ['build_agent']
