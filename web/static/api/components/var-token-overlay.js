/**
 * attachTokenOverlay(el, getVarsList) → { refresh(), el: wrap }
 *
 * Colors {{name}} tokens inside a plain <input> or <textarea> green/red by
 * whether the name is in the list getVarsList() returns, and shows a hover
 * tooltip with the variable's current value (or "not defined").
 *
 * Technique: the real element stays the source of truth for editing (value,
 * caret, selection, paste, any existing `{{` autocomplete wiring) — only its
 * text color is made transparent. A synced, pointer-events:none sibling <div>
 * (the "overlay") renders the same text with colored <span>s on top. Because
 * the overlay ignores pointer events, all clicks/typing still reach the real
 * element underneath; hover detection is done via mousemove rect-testing
 * against the overlay's own (visually on-top, but non-interactive) spans.
 */
import { tokenSpansIn, escapeHtml } from './var-style.js';

let _tooltipEl = null;
function _getTooltipEl() {
  if (_tooltipEl) return _tooltipEl;
  _tooltipEl = document.createElement('div');
  _tooltipEl.className = 'var-tooltip';
  _tooltipEl.style.display = 'none';
  document.body.appendChild(_tooltipEl);
  return _tooltipEl;
}

function _showTooltip(rect, name, entry) {
  const tip = _getTooltipEl();
  tip.innerHTML = entry
    ? `<strong>{{${escapeHtml(name)}}}</strong>` +
      `<div class="var-tooltip-value">${escapeHtml(String(entry.value ?? ''))}</div>` +
      (entry.group ? `<div class="var-tooltip-group">${escapeHtml(entry.group)}</div>` : '')
    : `<strong>{{${escapeHtml(name)}}}</strong>` +
      `<div class="var-tooltip-missing">Not defined in environment or collection</div>`;
  tip.style.display = 'block';
  const tipRect = tip.getBoundingClientRect();
  const below = window.innerHeight - rect.bottom;
  const top = below >= tipRect.height + 8 ? rect.bottom + 6 : rect.top - tipRect.height - 6;
  const left = Math.min(rect.left, window.innerWidth - tipRect.width - 8);
  tip.style.top = Math.max(4, top) + 'px';
  tip.style.left = Math.max(4, left) + 'px';
}

function _hideTooltip() {
  if (_tooltipEl) _tooltipEl.style.display = 'none';
}

export function attachTokenOverlay(el, getVarsList) {
  const isTextarea = el.tagName === 'TEXTAREA';

  const wrap = document.createElement('div');
  wrap.className = 'var-token-overlay-wrap';
  if (el.parentNode) el.parentNode.insertBefore(wrap, el);
  wrap.appendChild(el);

  const overlay = document.createElement('div');
  overlay.className = 'var-token-overlay' + (isTextarea ? ' var-token-overlay--multiline' : '');
  wrap.appendChild(overlay); // appended AFTER el so it paints on top; pointer-events:none lets clicks fall through

  const cs = getComputedStyle(el);
  const originalCaretColor = cs.color;
  [
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'fontFamily', 'fontSize', 'fontWeight', 'letterSpacing', 'lineHeight',
  ].forEach(prop => { overlay.style[prop] = cs[prop]; });

  el.style.color = 'transparent';
  el.style.caretColor = originalCaretColor;

  function _render() {
    const value = el.value;
    const list = getVarsList ? getVarsList() : null;
    let html = '';
    let last = 0;
    tokenSpansIn(value).forEach(({ name, start, end }) => {
      html += escapeHtml(value.slice(last, start));
      const known = list ? list.some(v => v.key === name) : null;
      const cls = known == null ? 'var-tok' : known ? 'var-tok var-tok--ok' : 'var-tok var-tok--missing';
      html += `<span class="${cls}">${escapeHtml(value.slice(start, end))}</span>`;
      last = end;
    });
    html += escapeHtml(value.slice(last));
    overlay.innerHTML = html;
    overlay.scrollLeft = el.scrollLeft;
    if (isTextarea) overlay.scrollTop = el.scrollTop;
  }

  el.addEventListener('input', _render);
  el.addEventListener('scroll', () => {
    overlay.scrollLeft = el.scrollLeft;
    if (isTextarea) overlay.scrollTop = el.scrollTop;
  });

  el.addEventListener('mousemove', (e) => {
    const spans = overlay.querySelectorAll('.var-tok--ok, .var-tok--missing');
    for (const span of spans) {
      const r = span.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        const name = span.textContent.replace(/^\{\{|\}\}$/g, '').trim();
        const list = getVarsList ? getVarsList() : null;
        const entry = list ? list.find(v => v.key === name) || null : null;
        _showTooltip(r, name, entry);
        return;
      }
    }
    _hideTooltip();
  });
  el.addEventListener('mouseleave', _hideTooltip);

  _render();

  return { refresh: _render, el: wrap };
}
