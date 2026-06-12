/**
 * app.js — Heartland Copilot console (voice-first client)
 * =======================================================
 * ES module. Adapted from soar-main's WebSocket client; surgical/CT/3D
 * machinery stripped, the 5 Heartland render layers added.
 *
 *   1. WebSocket lifecycle (/ws/{tenant_id}/{session_id})
 *   2. Audio I/O via AudioWorklets (16kHz mic up, 24kHz playback down)
 *   3. Barge-in handling (react to server events — don't predict locally)
 *   4. Render-command dispatch → render-layers.js
 *   5. Transcript + interaction log
 */

import { startAudioPlayerWorklet } from './audio-player.js';
import { startAudioRecorderWorklet, stopMicrophone } from './audio-recorder.js';
import {
  DocumentLayer, InventoryLayer, WorkflowLayer, KnowledgeLayer, ConfirmationLayer,
} from './render-layers.js';

// ── tenant ──────────────────────────────────────────────────────────────────
// One merchant per browser. tenant_id from ?merchant=, else a demo tenant.
const params   = new URLSearchParams(location.search);
const TENANT_ID = params.get('merchant') || 'demo_merchant';

// ── DOM ───────────────────────────────────────────────────────────────────
const orb        = document.getElementById('orb');
const statusLabel = document.getElementById('status-label');
const transcript  = document.getElementById('transcript');
const logList     = document.getElementById('log-list');

// ── state ─────────────────────────────────────────────────────────────────
let ws = null;
let audioPlayerNode = null, audioRecorderCtx = null, micStream = null;
let audioSuppressed = false, _lastSuppress = 0;
let currentCopilotEntry = null, currentMerchantEntry = null;
const _dispatched = new Map();
const DEDUP_MS = 4000;

orb.addEventListener('click', () => {
  if (ws && ws.readyState === WebSocket.OPEN) disconnect(); else connect();
});

function setStatus(s) {
  if (statusLabel) statusLabel.textContent = s;
  if (orb) orb.dataset.state = s;
}

// ── connection ──────────────────────────────────────────────────────────────
async function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  const sessionId = `session_${Date.now()}`;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws/${TENANT_ID}/${sessionId}`;
  setStatus('connecting');

  ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onopen = async () => {
    setStatus('active');
    try {
      [audioPlayerNode] = await startAudioPlayerWorklet();
      [, audioRecorderCtx, micStream] = await startAudioRecorderWorklet(onPcm);
    } catch (err) {
      setStatus('offline');
      logLine(`Audio failed: ${err.message || err}`);
    }
  };
  ws.onmessage = (e) => { if (typeof e.data === 'string') handleEvent(e.data); };
  ws.onclose = teardown;
  ws.onerror = () => { setStatus('offline'); };
}

function disconnect() { if (ws) { ws.close(); ws = null; } }

function teardown() {
  setStatus('offline');
  currentCopilotEntry = null; currentMerchantEntry = null;
  _dispatched.clear();
  if (micStream) { stopMicrophone(micStream); micStream = null; }
  if (audioRecorderCtx) { try { audioRecorderCtx.close(); } catch (_) {} audioRecorderCtx = null; }
  if (audioPlayerNode) {
    try {
      audioPlayerNode.port.postMessage({ command: 'endOfAudio' });
      audioPlayerNode.disconnect(); audioPlayerNode.context.close();
    } catch (_) {}
    audioPlayerNode = null;
  }
}

// ── audio ───────────────────────────────────────────────────────────────────
function onPcm(pcm) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(pcm); }

function bargeIn() {
  if (audioSuppressed) return;
  audioSuppressed = true; _lastSuppress = Date.now();
  if (audioPlayerNode) audioPlayerNode.port.postMessage({ command: 'endOfAudio' });
  currentCopilotEntry = null;
  setStatus('listening');
}

function b64ToBuf(b64) {
  const std = b64.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(std);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

// ── server events ────────────────────────────────────────────────────────────
function handleEvent(jsonString) {
  let event;
  try { event = JSON.parse(jsonString); } catch { return; }

  // Interaction log (server, on turnComplete)
  if (event.type === 'log' && event.entry) { logLine(event.entry.note); return; }
  // Localised transcript (SEA-LION, ADR-2) — replace the live Copilot bubble
  if (event.type === 'copilot_text') { upsert('copilot', event.text, true); return; }
  if (event.type === 'error') { logLine(`⚠ ${event.message || 'error'}`); return; }

  const inputText = event.inputTranscription?.text ?? event.input_transcription?.text;
  if (inputText) { bargeIn(); setStatus('listening'); upsert('merchant', inputText); }

  const outputText = event.outputTranscription?.text ?? event.output_transcription?.text;
  if (outputText) {
    if (Date.now() - _lastSuppress > 300) audioSuppressed = false;
    upsert('copilot', outputText);
  }

  if (event.author && event.author !== 'Heartland_Copilot') logLine(`→ ${event.author}`);

  for (const part of (event.content?.parts ?? [])) {
    const inline = part.inlineData ?? part.inline_data;
    const mime = inline?.mimeType ?? inline?.mime_type ?? '';
    if (inline && mime.startsWith('audio/pcm') && audioPlayerNode && !audioSuppressed) {
      setStatus('speaking');
      audioPlayerNode.port.postMessage(b64ToBuf(inline.data));
    }
    if (part.text && event.content?.role === 'model' && !outputText) upsert('copilot', part.text);

    const fc = part.functionCall ?? part.function_call;
    if (fc) {
      const key = `${fc.name}:${JSON.stringify(fc.args ?? {})}`;
      const now = Date.now();
      if (now - (_dispatched.get(key) ?? 0) > DEDUP_MS) {
        _dispatched.set(key, now);
        logLine(`▶ ${fc.name}`);
      }
    }
    const fr = part.functionResponse ?? part.function_response;
    if (fr) handleFunctionResponse(fr);
  }

  if (event.interrupted) bargeIn();
  if (event.turnComplete ?? event.turn_complete) {
    currentMerchantEntry = null;
    if (ws && ws.readyState === WebSocket.OPEN) setStatus('active');
  }
}

// ── render dispatch (ADR-5) ──────────────────────────────────────────────────
function handleFunctionResponse(fr) {
  const cmd = fr.response?.render_command;
  if (!cmd) return;
  switch (cmd.layer) {
    case 'document':     DocumentLayer.show(cmd); break;
    case 'inventory':    InventoryLayer.show(cmd); break;
    case 'workflow':
      if (cmd.action === 'needs_info') WorkflowLayer.needsInfo(cmd);
      else WorkflowLayer.show(cmd);
      break;
    case 'knowledge':    KnowledgeLayer.show(cmd); break;
    case 'confirmation':
      if (cmd.action === 'executed') ConfirmationLayer.executed(cmd);
      else if (cmd.action === 'cancelled') ConfirmationLayer.cancelled(cmd);
      else ConfirmationLayer.show(cmd);
      break;
    default: console.warn('[app.js] unknown render layer:', cmd.layer);
  }
}

// ── transcript + log ─────────────────────────────────────────────────────────
function upsert(speaker, text, replace = false) {
  if (!text) return;
  // Drop the "your conversation appears here" placeholder on first real line.
  const hint = transcript.querySelector('.empty-hint');
  if (hint) hint.remove();
  let entry = speaker === 'merchant' ? currentMerchantEntry : currentCopilotEntry;
  if (!entry || replace) {
    if (replace && entry) entry.remove();
    entry = document.createElement('div');
    entry.className = `bubble ${speaker}`;
    transcript.appendChild(entry);
    if (speaker === 'merchant') currentMerchantEntry = entry; else currentCopilotEntry = entry;
  }
  entry.textContent = text;
  transcript.scrollTop = transcript.scrollHeight;
}

function logLine(text) {
  if (!logList) return;
  const li = document.createElement('div');
  li.className = 'log-line';
  li.textContent = text;
  logList.appendChild(li);
  logList.scrollTop = logList.scrollHeight;
}
