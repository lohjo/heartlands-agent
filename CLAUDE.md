# Heartland Commons — Engineering Notes

Voice-first AI platform for Singapore heartland merchants. Three parts, built in
order: **Copilot core** (this phase) → Discovery Trail + Digital Passport →
Volunteer Management System.

Adapted from **soar-main** (surgical AI orchestration, Google ADK + Gemini Live).
Infrastructure patterns kept; all medical domain content stripped.

## Non-negotiables (check every decision against these)
- **Zero recurring cost per merchant.** Free-tier / self-hostable only.
- **Voice-first.** Hands-free, natural barge-in. Binding constraint.
- **PDPA.** All merchant data in Singapore (`asia-southeast1`). Per-tenant isolation.
- **Dev velocity.** Two-person team. No Kubernetes. No per-tenant Cloud Run for standard tier.
- **Progressive trust.** Incomplete `tenant_config` is the normal state; missing
  fields get fallback language, never errors or hallucinated data.

## Region strategy (decided)
Split, because Gemini Live native-audio is not in `asia-southeast1` yet:
- **Gemini Live model → `us-central1`** (`GOOGLE_CLOUD_LOCATION`). The live audio
  session transits a US region — documented PDPA caveat.
- **Firestore + ALL stored merchant data → `asia-southeast1`** (database location,
  fixed at creation). The client only names the project + database id.

## Locked ADRs (1–6 — build on these, do not relitigate)
1. **Agent topology.** Hub-and-spoke. *Session-owning* sub-agents (Onboarding,
   Quote, Training) stay active until an exit phrase — Screen_Advisor pattern.
   *Ephemeral* sub-agents (HECS_Lookup, Supplier_Info) execute→speak→transfer
   back — Briefing pattern. Root handles multi-action + routing only.
   → `app/soar_orchestrator/subagents/{session_owning,ephemeral}.py`
2. **SEA-LION.** Pattern B middleware in `downstream_task()`. On turnComplete,
   if locale ∈ {`sg-en`,`zh-sg`}, `localize_text()` the displayed transcript
   before sending. Display text only — never the audio. Self-hosted only.
   → `app/shared/localize.py`, `app/main.py`
3. **Per-tenant state.** `FirestoreSessionService` replaces InMemory. No
   module-level mutable state in `tools.py` — all in `tool_context.state`.
   `build_agent(tenant_config)` factory, not a singleton.
   → `app/shared/firestore_session.py`, `app/soar_orchestrator/agent.py`
4. **HITL.** Stage → confirm. Every high-risk action is a tool pair:
   `stage_[action]()` → confirmation card; `execute_staged_action(action_id)`
   after the merchant says "confirm". Voice is the confirmation channel.
   → `app/soar_orchestrator/tools.py`
5. **Tool contract.** `render_command` optional, enforced via `_DISPLAY_TOOLS`.
   Valid layers: `document | inventory | workflow | knowledge | confirmation`.
   Tool docstrings carry Singlish→param mappings. (Checklist below.)
6. **Deployment.** Single shared Cloud Run service; per-tenant logical isolation
   in Firestore. Staging gate (PR → staging, manual prod promote). Dedicated
   tier = same image, different infra flag.

## Open ADRs (7–10 — decisions made so far)
- **ADR-7 (Onboarding).** Persona is a **prompt-layer switch** on one shared
  agent build, keyed by `tenant_config['onboarding_stage']` (1 = back-office
  listening persona; 2+ = ambient in-store). Not a separate agent.
  → `app/soar_orchestrator/personas.py`
- **ADR-8 (Frontend).** Vanilla HTML/CSS/JS, responsive, warm/local visual
  language. 5 render layers as independent panels (`render-layers.js`).
- **ADR-9 (HECS).** Contextual micro-sessions via `Training_Agent`; placeholder
  content for v1 (partnership pending).
- **ADR-10 (Workflows).** v1 = dead-time tasks (inventory, WhatsApp draft,
  grants, photo tips). New workflows = new sub-agent + tool pair, no core change.

## Checklist — adding a NEW render layer (ADR-5)
A new layer requires a change in **three places simultaneously**:
1. `app/soar_orchestrator/tools.py` — return `render_command.layer = '<new>'`.
2. `app/static/js/app.js` — add a `case '<new>':` in `handleFunctionResponse`
   (and a panel in `render-layers.js`).
3. `app/soar_orchestrator/agent.py` — add the tool to `_DISPLAY_TOOLS` and the
   layer to `_VALID_LAYERS`.
Miss one and the after-tool callback rejects the tool (a missing render is an
error for display tools, never a silent no-op).

## Map: soar-main → Heartland
| soar-main | Heartland | Why |
|---|---|---|
| `InMemorySessionService` | `FirestoreSessionService` | ADR-3 per-tenant persistence |
| module `root_agent` | `build_agent(tenant_config)` | ADR-3 per-tenant build |
| module-level `_ct_state` etc. | `tool_context.state` | ADR-3 |
| `_grounding_after_tool` (always) | `_validate_after_tool` (`_DISPLAY_TOOLS` only) | ADR-5 selective |
| FHIR/CT/3D/drug tools | merchant tools | domain swap |
| Screen_Advisor (stay active) | session-owning sub-agents | ADR-1 |
| Briefing_Agent (hand back) | ephemeral sub-agents | ADR-1 |

## Run locally
See `README.md`. TL;DR: `pip install -e .`, `cp app/.env.template app/.env`,
then **from inside `app/`**: `uvicorn main:app --reload --port 8080`.
Console at `/console`. Without GCP creds the app still runs (Firestore + Vertex
degrade gracefully; voice needs Vertex).
