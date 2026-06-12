"""
Interaction logging — Heartland Commons
=======================================
Every merchant <-> Copilot exchange is logged. This is not optional plumbing —
it serves two first-class product goals:

  1. Outcome tracking (success criterion #5): the logs answer "how did we
     enhance business competitiveness and public appeal?" They are the raw
     material for analytics.
  2. The knowledge-transfer layer: when a student volunteer arrives for a
     session, they read these logs to understand the merchant's ACTUAL needs
     before walking in. The Copilot is the bridge between a merchant's decades
     of operational experience and the students trying to help.

Storage: Firestore `tenants/{tenant_id}/interactions` (asia-southeast1, PDPA),
plus a small in-memory tail per session for the live console. Best-effort —
a logging failure never interrupts a voice turn.

Mirrors the soar-main `log_ai_interaction` shape so the frontend log panel is a
straight reuse.
"""

import datetime
import logging

from shared.firestore import get_db

logger = logging.getLogger('heartland.interaction_log')

# Per-session in-memory tail (session_id -> list[entry]) for the console UI.
# Bounded so a long-running session can't grow memory without limit on a
# Cloud Run instance (durable history lives in Firestore, not here).
_MAX_TAIL = 50
_session_tail: dict[str, list] = {}


def _trunc(s: str, maxlen: int = 90) -> str:
    s = (s or '').strip()
    return (s[:maxlen] + '…') if len(s) > maxlen else s


def log_interaction(tenant_id: str, session_id: str,
                    merchant_said: str, copilot_said: str) -> dict | None:
    """Record one exchange. Returns the entry (for the UI) or None if empty.

    Called server-side from main.py on turnComplete — NOT an agent tool.
    """
    merchant_said = (merchant_said or '').strip()
    copilot_said = (copilot_said or '').strip()
    if not merchant_said and not copilot_said:
        return None

    now = datetime.datetime.now(datetime.timezone.utc)
    parts = []
    if merchant_said:
        parts.append(f'Merchant: {_trunc(merchant_said)}')
    if copilot_said:
        parts.append(f'Copilot: {_trunc(copilot_said)}')

    entry = {
        'type': 'interaction',
        'note': ' | '.join(parts),
        'merchant_said': merchant_said,
        'copilot_said': copilot_said,
        'timestamp': now.strftime('%H:%M:%S'),
    }

    tail = _session_tail.setdefault(session_id, [])
    tail.append(entry)
    if len(tail) > _MAX_TAIL:
        del tail[:-_MAX_TAIL]

    db = get_db()
    if db is not None:
        try:
            db.collection('tenants').document(tenant_id) \
              .collection('interactions').add({**entry, 'session_id': session_id, 'ts': now})
        except Exception as exc:
            logger.warning('interaction persist failed for %s (%s).', tenant_id, exc)

    return entry


def session_history(session_id: str) -> list:
    """The in-memory tail for one session (console reuse / student preview)."""
    return list(_session_tail.get(session_id, []))
