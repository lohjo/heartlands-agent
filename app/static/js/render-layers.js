/**
 * render-layers.js — Heartland Copilot display layers (ADR-5)
 * ===========================================================
 * One handler object per valid render layer. The agent's tools return a
 * `render_command` with a `layer`; app.js routes it here. Adding a NEW layer
 * is a 3-place change (tools.py, this file's dispatch in app.js, agent.py
 * _DISPLAY_TOOLS) — see CLAUDE.md.
 *
 * Valid layers: document | inventory | workflow | knowledge | confirmation
 *
 * Each panel renders into #layer-stack as a warm, paper-like card. The visual
 * language is intentionally local and friendly, not startup-sterile — it must
 * be showable to a 60-year-old minimart owner.
 */

const stack = () => document.getElementById('layer-stack');

function card(id, html) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    el.className = 'layer-card';
    stack().prepend(el);
  }
  el.innerHTML = html;
  el.classList.remove('hidden');
  // gentle entrance
  el.classList.remove('pop'); void el.offsetWidth; el.classList.add('pop');
  return el;
}

function hideCard(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ── document: rendered promo / quote / invoice card ─────────────────────────
export const DocumentLayer = {
  show(cmd) {
    card('layer-document', `
      <div class="layer-head"><span class="layer-tag tag-doc">${esc(cmd.doc_type || 'document')}</span>
        <span class="layer-title">${esc(cmd.title || 'Document')}</span></div>
      <div class="doc-shop">${esc(cmd.shop || '')}</div>
      <div class="doc-body">${esc(cmd.body || '')}</div>
      <div class="layer-foot">Say “send it” to share, or tell me what to change.</div>`);
  },
};

// ── inventory: stock panel ──────────────────────────────────────────────────
export const InventoryLayer = {
  show(cmd) {
    const all = cmd.all || {};
    const rows = Object.keys(all).length
      ? Object.entries(all).map(([k, v]) => `
          <div class="inv-row ${k === cmd.category ? 'inv-hit' : ''}">
            <span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')
      : `<div class="inv-row inv-hit"><span>${esc(cmd.category)}</span><b>${esc(cmd.quantity)}</b></div>`;
    card('layer-inventory', `
      <div class="layer-head"><span class="layer-tag tag-inv">stock</span>
        <span class="layer-title">What you have</span></div>
      <div class="inv-list">${rows}</div>`);
  },
};

// ── workflow: status tracker / needs-info nudge ─────────────────────────────
export const WorkflowLayer = {
  show(cmd) {
    const items = cmd.items || [];
    const body = items.length
      ? items.map(i => `
          <div class="wf-row wf-${esc(i.status)}">
            <span class="wf-dot"></span>
            <div><div>${esc(i.summary || i.type)}</div>
              <div class="wf-status">${esc((i.status || '').replace(/_/g, ' '))}</div></div>
          </div>`).join('')
      : `<div class="wf-empty">Nothing pending. All clear ✓</div>`;
    card('layer-workflow', `
      <div class="layer-head"><span class="layer-tag tag-wf">tasks</span>
        <span class="layer-title">What's pending</span></div>
      <div class="wf-list">${body}</div>`);
  },
  needsInfo(cmd) {
    card('layer-workflow', `
      <div class="layer-head"><span class="layer-tag tag-wf">let's learn</span></div>
      <div class="wf-needs">${esc(cmd.message)}</div>`);
  },
};

// ── knowledge: HECS / grant / tips content ──────────────────────────────────
export const KnowledgeLayer = {
  show(cmd) {
    const bullets = (cmd.bullets || []).map(b => `<li>${esc(b)}</li>`).join('');
    card('layer-knowledge', `
      <div class="layer-head"><span class="layer-tag tag-know">learn</span>
        <span class="layer-title">${esc(cmd.title || 'Good to know')}</span></div>
      ${cmd.body ? `<div class="know-body">${esc(cmd.body)}</div>` : ''}
      ${bullets ? `<ul class="know-list">${bullets}</ul>` : ''}
      <div class="layer-foot">${esc(cmd.source || '')}</div>`);
  },
};

// ── confirmation: HITL stage-and-confirm card (ADR-4) ───────────────────────
export const ConfirmationLayer = {
  show(cmd) {
    card('layer-confirmation', `
      <div class="layer-head"><span class="layer-tag tag-confirm">confirm?</span>
        <span class="layer-title">${esc((cmd.action_type || '').replace(/_/g, ' '))}</span></div>
      <div class="confirm-preview">${esc(cmd.preview)}</div>
      <div class="confirm-actions">
        <span class="confirm-yes">Say “confirm” ✓</span>
        <span class="confirm-no">or “cancel”</span>
      </div>`);
  },
  executed(cmd) {
    card('layer-confirmation', `
      <div class="layer-head"><span class="layer-tag tag-done">done ✓</span>
        <span class="layer-title">${esc((cmd.action_type || '').replace(/_/g, ' '))}</span></div>
      <div class="confirm-preview done">${esc(cmd.preview)}</div>
      <div class="layer-foot">Done and logged.</div>`);
  },
  cancelled() { hideCard('layer-confirmation'); },
};
