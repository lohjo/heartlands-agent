"""
SEA-LION localisation middleware — Heartland Commons (ADR-2)
===========================================================
Pattern B: transparent post-processing middleware. The Copilot's audio stream
is untouched — SEA-LION only ever sees DISPLAYED TEXT. When the merchant's
locale is `sg-en` or `zh-sg`, the final transcript line is passed through a
SELF-HOSTED SEA-LION endpoint before it is forwarded to the browser, so the
on-screen text reads in natural Singlish / Singapore Mandarin rather than the
model's default register.

Hard constraints from the prompt:
  - Self-hosted only. Never route merchant content through any external
    SEA-LION API. `SEA_LION_URL` must point at our own Cloud Run service.
  - Display text only. Do NOT touch the audio blob.
  - v1: the SEA-LION service is not stood up yet. If `SEA_LION_URL` is unset
    this function is an identity pass-through — the product still works, the
    text is just un-localised. Never error, never block the stream.
"""

import logging
import os

import httpx

logger = logging.getLogger('heartland.localize')

SEA_LION_URL = os.environ.get('SEA_LION_URL', '').strip()
_LOCALES = {'sg-en', 'zh-sg'}
_TIMEOUT = 4.0


async def localize_text(text: str, locale: str) -> str:
    """Return `text` rewritten for `locale` via self-hosted SEA-LION.

    Identity pass-through when: text is empty, locale is not a SEA-LION locale,
    no endpoint is configured, or the call fails for any reason. The displayed
    transcript is best-effort polish — it must never break a merchant turn.
    """
    text = (text or '').strip()
    if not text or locale not in _LOCALES or not SEA_LION_URL:
        return text
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(SEA_LION_URL, json={'text': text, 'locale': locale})
            resp.raise_for_status()
            data = resp.json()
            return (data.get('text') or text).strip()
    except Exception as exc:
        logger.warning('SEA-LION localize failed (%s) — returning original text.', exc)
        return text
