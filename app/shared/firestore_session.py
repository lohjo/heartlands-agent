"""
FirestoreSessionService — Heartland Commons (ADR-3)
===================================================
Replaces ADK's InMemorySessionService. soar-main kept all session state in
process memory and all tool state at module level; neither survives a Cloud Run
instance recycle and neither isolates tenants. ADR-3 moves both to Firestore.

Design (pragmatic, two-person team, near-zero ops — ADR / dev-velocity):
This is a WRITE-THROUGH layer over InMemorySessionService, not a from-scratch
re-implementation of the ADK event protocol. The live turn loop stays in-memory
(fast, ADK-native); we hydrate per-tenant state on session create and persist it
back on demand (called from main.py on turnComplete). What we persist is the
durable, PDPA-relevant payload: `session.state` — which now holds tenant_config,
staged HITL actions, and remembered facts (all the module-level dicts that used
to live in tools.py).

Per-tenant isolation (ADR-6): state is stored at
`tenants/{user_id}/sessions/{session_id}` — user_id IS the tenant_id. One
merchant's session documents can never collide with another's.

Graceful degradation: if Firestore is unavailable this behaves exactly like
InMemorySessionService, so local dev needs no cloud credentials.
"""

import logging

from google.adk.sessions import InMemorySessionService

from shared.firestore import get_db

logger = logging.getLogger('heartland.session')


class FirestoreSessionService(InMemorySessionService):
    """InMemory session semantics + Firestore-backed per-tenant state."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db = get_db()

    # -- persistence helpers --------------------------------------------------

    def _doc(self, app_name: str, user_id: str, session_id: str):
        # user_id == tenant_id → per-tenant document subtree.
        return (self._db.collection('tenants').document(user_id)
                .collection('sessions').document(session_id))

    def _load_state(self, app_name: str, user_id: str, session_id: str) -> dict:
        if self._db is None or not session_id:
            return {}
        try:
            snap = self._doc(app_name, user_id, session_id).get()
            if snap.exists:
                return (snap.to_dict() or {}).get('state', {}) or {}
        except Exception as exc:
            logger.warning('session state load failed (%s).', exc)
        return {}

    def persist(self, session) -> None:
        """Write session.state back to Firestore. Call after meaningful turns.

        Best-effort; a persistence failure must not interrupt a merchant.
        """
        if self._db is None or session is None:
            return
        user_id = getattr(session, 'user_id', None)
        session_id = getattr(session, 'id', None) or getattr(session, 'session_id', None)
        app_name = getattr(session, 'app_name', 'heartland')
        if not user_id or not session_id:
            return
        try:
            state = dict(getattr(session, 'state', {}) or {})
            self._doc(app_name, user_id, session_id).set({'state': state}, merge=True)
        except Exception as exc:
            logger.warning('session state persist failed (%s).', exc)

    # -- overrides ------------------------------------------------------------

    async def create_session(self, *, app_name, user_id, session_id=None,
                             state=None, **kwargs):
        """Hydrate any persisted state, then layer caller-supplied state on top.

        Caller-supplied `state` wins (it carries the freshly-loaded
        tenant_config seeded by main.py), with persisted session state filling
        in anything carried over from a previous connection.
        """
        persisted = self._load_state(app_name, user_id, session_id)
        merged = {**persisted, **(state or {})}
        return await super().create_session(
            app_name=app_name, user_id=user_id, session_id=session_id,
            state=merged or None, **kwargs,
        )
