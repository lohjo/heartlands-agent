"""
Tenant configuration — Heartland Commons (ADR-3 / ADR-7)
=======================================================
A merchant's `tenant_config` is the progressively-built knowledge the Copilot
has about their business. It starts almost empty (session 1: just a name and a
shop type, observed by the student team) and grows through conversation —
suppliers by session 3, full categories by session 5+, and it is NEVER
complete for a traditional operator. That is by design (ADR-7).

The cardinal rule (progressive trust model): a missing field must produce
FALLBACK LANGUAGE, never an error and never a hallucinated value. The Copilot
says "tell me who your rice supplier is and I'll remember for next time" — it
does not crash and does not invent "Lim Huat Rice Pte Ltd".

Storage: Firestore `tenants/{tenant_id}` (asia-southeast1, per PDPA). When
Firestore is unavailable the config lives only in memory for the session.

Per-tenant isolation (ADR-6): every read/write is scoped to one tenant_id doc.
"""

import logging
from typing import Any, Optional

from shared.firestore import get_db

logger = logging.getLogger('heartland.tenant_config')

_COLLECTION = 'tenants'

# In-memory fallback store, keyed by tenant_id. Used only when Firestore is
# unavailable so the prototype still runs end-to-end.
_memory_store: dict[str, dict] = {}


def default_config(tenant_id: str) -> dict:
    """A brand-new merchant — session 1, almost nothing known yet (ADR-7)."""
    return {
        'tenant_id': tenant_id,
        'onboarding_stage': 1,          # 1 = first listening session (back-office persona)
        'merchant_name': None,          # "Auntie Lim"
        'shop_name': None,              # "Lim Provision Shop"
        'shop_type': None,              # "minimart", "kopitiam", "tailor"
        'locale': 'sg-en',              # sg-en | zh-sg  (drives SEA-LION, ADR-2)
        'languages': ['sg-en'],
        'product_categories': [],       # filled by ~session 3
        'suppliers': {},                # {'rice': 'Lim Huat', ...} — by ~session 3
        'inventory': {},                # {'rice': '12 bags', ...} — corrected by ~session 5
        'facts': {},                    # free-form remembered facts (progressive trust)
    }


def load_tenant_config(tenant_id: str) -> dict:
    """Load a merchant's config, or a minimal default if they are brand new.

    Never raises. Merges persisted fields over the default so a config written
    by an older code version (missing newer keys) still has every key present.
    """
    base = default_config(tenant_id)
    db = get_db()
    if db is None:
        stored = _memory_store.get(tenant_id)
        return {**base, **stored} if stored else base
    try:
        snap = db.collection(_COLLECTION).document(tenant_id).get()
        if snap.exists:
            return {**base, **(snap.to_dict() or {})}
    except Exception as exc:
        logger.warning('load_tenant_config failed for %s (%s) — using default.', tenant_id, exc)
    return base


def save_tenant_config(tenant_id: str, config: dict) -> None:
    """Persist the whole config. Best-effort; never raises into a live session."""
    config = {**config, 'tenant_id': tenant_id}
    db = get_db()
    if db is None:
        _memory_store[tenant_id] = config
        return
    try:
        db.collection(_COLLECTION).document(tenant_id).set(config, merge=True)
    except Exception as exc:
        logger.warning('save_tenant_config failed for %s (%s).', tenant_id, exc)
        _memory_store[tenant_id] = config


def remember_fact(tenant_id: str, field: str, value: Any) -> dict:
    """Progressive-trust write: stash a single learned fact and persist it.

    `field` may be a top-level key (e.g. 'shop_type') or a free-form fact
    (e.g. 'rice_supplier'). Top-level keys update the structured config;
    everything else lands in `facts` so nothing is ever lost.
    Returns the updated config.
    """
    config = load_tenant_config(tenant_id)
    field = (field or '').strip()
    if not field:
        return config

    # Supplier shorthand: "<x>_supplier" → suppliers[x]
    if field.endswith('_supplier'):
        category = field[: -len('_supplier')]
        config.setdefault('suppliers', {})[category] = value
    elif field in config and field not in ('tenant_id', 'onboarding_stage'):
        config[field] = value
    else:
        config.setdefault('facts', {})[field] = value

    save_tenant_config(tenant_id, config)
    return config


def field_or_fallback(config: dict, field: str, fallback: Optional[str] = None) -> Optional[str]:
    """Look up a field across structured keys, suppliers, and facts.

    Returns the value if known, else `fallback` (default None). The CALLER is
    responsible for turning a None into natural fallback language — this never
    invents data.
    """
    if not config:
        return fallback
    if config.get(field) not in (None, '', [], {}):
        return config[field]
    if field.endswith('_supplier'):
        category = field[: -len('_supplier')]
        val = (config.get('suppliers') or {}).get(category)
        if val:
            return val
    val = (config.get('facts') or {}).get(field)
    return val if val not in (None, '', [], {}) else fallback
