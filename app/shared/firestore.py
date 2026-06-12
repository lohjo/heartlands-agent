"""
Firestore client accessor — Heartland Commons
=============================================
Single cached Firestore handle shared by the session service, tenant_config,
and interaction log. Every module that touches durable merchant data goes
through get_db() so there is exactly one client and one place to reason about
region and PDPA residency.

PDPA (non-negotiable): the Firestore database MUST be provisioned in
`asia-southeast1`. The database location is fixed at creation time in GCP and
is not selectable from the client — this module only names the project and the
database id. See README "Region strategy": the Gemini Live model runs in
us-central1 (native-audio availability) while ALL stored merchant data stays in
asia-southeast1.

Graceful degradation: if google-cloud-firestore is not installed or no project
is configured (e.g. a laptop with no gcloud auth), get_db() returns None and
callers fall back to in-memory behaviour. The prototype still runs; it just
does not persist across restarts.
"""

import logging
import os

logger = logging.getLogger('heartland.firestore')

# Firestore database id. Default '(default)'. The database behind this id must
# be created in asia-southeast1 for PDPA residency.
FIRESTORE_DATABASE = os.environ.get('FIRESTORE_DATABASE', '(default)')

_db = None
_initialised = False


def get_db():
    """Return a cached Firestore client, or None if unavailable.

    Never raises — a missing client degrades to in-memory mode rather than
    taking down a merchant session.
    """
    global _db, _initialised
    if _initialised:
        return _db
    _initialised = True

    project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    if not project:
        logger.warning('GOOGLE_CLOUD_PROJECT unset — Firestore disabled (in-memory mode).')
        _db = None
        return _db

    try:
        from google.cloud import firestore
        _db = firestore.Client(project=project, database=FIRESTORE_DATABASE)
        logger.info('Firestore connected: project=%s database=%s', project, FIRESTORE_DATABASE)
    except Exception as exc:  # ImportError, DefaultCredentialsError, etc.
        logger.warning('Firestore unavailable (%s) — running in-memory.', exc)
        _db = None
    return _db
