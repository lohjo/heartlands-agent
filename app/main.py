"""
Heartland Commons — FastAPI Server (main.py)
============================================
Wires ADK's LiveRequestQueue to the browser over a WebSocket, adapted from
soar-main's voice console. The dual-task loop (upstream/downstream) and the
asyncio.wait(FIRST_EXCEPTION) lifecycle are kept verbatim — they are the proven
ADK run_live pattern.

What changed from soar-main, per ADR:
  ADR-3  Per-tenant. The agent is built per connection by build_agent(
         tenant_config), and sessions use FirestoreSessionService, not
         InMemorySessionService. tenant_config is loaded from Firestore and
         seeded into session.state.
  ADR-2  SEA-LION. On turnComplete we localise the displayed transcript via
         localize_text() (self-hosted, display-text only) before sending it to
         the browser. The audio stream is untouched.
  Logging. Every exchange is recorded by log_interaction (analytics + the
         student knowledge-transfer layer).

CRITICAL: run uvicorn from INSIDE app/ so `soar_orchestrator` imports:
    cd app/
    uvicorn main:app --reload --port 8080
"""

import asyncio
import base64
from contextlib import aclosing
import json
import logging
import os

from dotenv import load_dotenv

# load_dotenv BEFORE importing soar_orchestrator so DEMO_AGENT_MODEL is set when
# agent.py reads os.environ at import time.
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

from soar_orchestrator import build_agent
from shared.firestore_session import FirestoreSessionService
from shared.tenant_config import load_tenant_config
from shared.interaction_log import log_interaction
from shared.localize import localize_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('heartland')

APP_NAME = 'heartland'
DEMO_AGENT_MODEL = os.environ.get('DEMO_AGENT_MODEL', '')
# Warm, natural prebuilt voice for the Copilot.
COPILOT_VOICE = os.environ.get('COPILOT_VOICE', 'Aoede')

# Shared per-tenant session service (ADR-3). Reads/writes are scoped per tenant.
session_service = FirestoreSessionService()

app = FastAPI(title='Heartland Commons — Copilot')

app.mount('/static', StaticFiles(directory='static'), name='static')


@app.get('/')
async def landing():
    return FileResponse('static/landing.html')


@app.get('/console')
async def console():
    return FileResponse('static/index.html')


@app.get('/healthz')
async def healthz():
    return {'status': 'ok'}


@app.websocket('/ws/{tenant_id}/{session_id}')
async def websocket_endpoint(websocket: WebSocket, tenant_id: str, session_id: str):
    """One WebSocket per merchant session.

    user_id == tenant_id (per-tenant isolation, ADR-6). Runs two concurrent
    tasks: upstream (browser → Vertex) and downstream (Vertex → browser).
    """
    await websocket.accept()
    logger.info('WS connected: tenant=%s session=%s', tenant_id, session_id)

    # ADR-3: load this merchant's progressively-built config and build a
    # per-tenant agent + runner. An incomplete config is fine — persona uses
    # fallback language (ADR-7).
    tenant_config = load_tenant_config(tenant_id)
    agent = build_agent(tenant_config)
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    locale = tenant_config.get('locale', 'sg-en')

    is_native_audio = any(s in DEMO_AGENT_MODEL for s in ('native-audio', 'native', 'live'))
    if is_native_audio:
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=['AUDIO'],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=COPILOT_VOICE)
                )
            ),
        )
    else:
        run_config = RunConfig(streaming_mode=StreamingMode.BIDI, response_modalities=['TEXT'])

    # Get or create session; seed tenant_config into state so tools can read it.
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=tenant_id, session_id=session_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=tenant_id, session_id=session_id,
            state={'tenant_config': tenant_config},
        )
        logger.info('Created session %s', session_id)
    else:
        session.state['tenant_config'] = tenant_config
        logger.info('Resumed session %s', session_id)

    live_request_queue = LiveRequestQueue()

    async def upstream_task():
        """Browser → Vertex AI. Binary frames are PCM audio; JSON is text."""
        _AUDIO_CHUNK_BYTES = 3200  # 100ms @ 16kHz s16le mono
        _audio_buf = bytearray()
        while True:
            message = await websocket.receive()
            if 'bytes' in message and message['bytes']:
                _audio_buf.extend(message['bytes'])
                while len(_audio_buf) >= _AUDIO_CHUNK_BYTES:
                    chunk = bytes(_audio_buf[:_AUDIO_CHUNK_BYTES])
                    del _audio_buf[:_AUDIO_CHUNK_BYTES]
                    # Vertex Live requires exactly 'audio/pcm' (no rate suffix).
                    live_request_queue.send_realtime(types.Blob(data=chunk, mime_type='audio/pcm'))
            elif 'text' in message and message['text']:
                try:
                    payload = json.loads(message['text'])
                except json.JSONDecodeError:
                    continue
                if payload.get('type') == 'text' and payload.get('content'):
                    live_request_queue.send_content(
                        types.Content(role='user', parts=[types.Part(text=payload['content'])])
                    )

    async def downstream_task():
        """Vertex AI → browser. Forwards events; localises the transcript and
        logs each exchange on turnComplete (ADR-2 + interaction logging)."""
        _merchant_said = ''
        _copilot_said = ''
        async with aclosing(runner.run_live(
            session=session, live_request_queue=live_request_queue, run_config=run_config,
        )) as live_events:
          try:
            async for event in live_events:
                event_json = event.model_dump_json(exclude_none=True, by_alias=True)
                await websocket.send_text(event_json)
                event_dict = json.loads(event_json)

                input_text = (event_dict.get('inputTranscription', {}).get('text')
                              or event_dict.get('input_transcription', {}).get('text'))
                if input_text:
                    _merchant_said = input_text

                output_text = (event_dict.get('outputTranscription', {}).get('text')
                               or event_dict.get('output_transcription', {}).get('text'))
                if output_text:
                    _copilot_said = output_text

                if event_dict.get('turnComplete') or event_dict.get('turn_complete'):
                    # ADR-2: localise the DISPLAYED transcript (audio already
                    # streamed untouched). Self-hosted SEA-LION; no-op if unset.
                    localized = await localize_text(_copilot_said, locale)
                    if localized:
                        await websocket.send_text(json.dumps({
                            'type': 'copilot_text', 'text': localized,
                        }))
                    entry = log_interaction(tenant_id, session_id, _merchant_said, _copilot_said)
                    if entry:
                        await websocket.send_text(json.dumps({'type': 'log', 'entry': entry}))
                    # Persist per-tenant session state (staged actions, facts).
                    session_service.persist(session)
                    _merchant_said = ''
                    _copilot_said = ''
          except (ValueError, KeyError, TypeError) as exc:
            logger.warning('Recoverable live error: %s', exc)
            try:
                await websocket.send_text(json.dumps({'type': 'error', 'message': f'Session error: {exc}'}))
            except Exception:
                pass
            raise

    up = asyncio.create_task(upstream_task())
    down = asyncio.create_task(downstream_task())
    done, pending = await asyncio.wait([up, down], return_when=asyncio.FIRST_EXCEPTION)
    try:
        for task in done:
            task.result()
    except WebSocketDisconnect:
        logger.info('Client disconnected: %s', session_id)
    except Exception as exc:
        logger.error('Live session error %s: %s', session_id, exc, exc_info=True)
    finally:
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        live_request_queue.close()
        session_service.persist(session)
        logger.info('Session closed: %s', session_id)
        try:
            await websocket.close()
        except Exception:
            pass
