/**
 * createJsonEditor({ parent, value, isDark, onChange, getVarsList }) → Promise<editor|null>
 * Uses the bundled CM6 from window.CM6 (vendor/codemirror/cm6.js).
 * Returns null if CM6 unavailable.
 * getVarsList?: () => Array<{key, value, group?}>|null — when provided AND
 * the vendor bundle exposes Decoration/ViewPlugin/RangeSetBuilder/
 * StateEffect/hoverTooltip, {{name}} tokens in the doc get colored
 * (var-tok--ok/--missing) and a hover tooltip shows the current value or
 * "not defined". Silently skipped on older bundles (see REBUILD.md).
 * editor: { getValue(), setValue(str), refresh(), focus(), destroy() }
 */
import { tokenSpansIn, escapeHtml } from './var-style.js';

export async function createJsonEditor({ parent, value = '', isDark = true, onChange, getVarsList }) {
  try {
    const CM = window.CM6;
    if (!CM) throw new Error('CM6 vendor bundle not loaded');

    const { EditorView, EditorState, basicSetup, json, jsonParseLinter, linter, lintGutter, oneDark } = CM;
    const { Decoration, ViewPlugin, RangeSetBuilder, StateEffect, hoverTooltip } = CM;

    // Custom linter that understands {{VAR}} template syntax
    const varAwareLinter = linter((view) => {
      const text = view.state.doc.toString().trim();
      if (!text) return [];
      const subbed = text.replace(/\{\{[^}]+\}\}/g, '"__QCVAR__"');
      try { JSON.parse(subbed); return []; }
      catch (e) {
        const m = /at position (\d+)/i.exec(e.message) || /position (\d+)/i.exec(e.message);
        const pos = m ? Math.min(+m[1], text.length - 1) : 0;
        return [{ from: pos, to: Math.min(pos + 1, text.length), severity: 'error', message: e.message }];
      }
    });

    const baseTheme = EditorView.theme({
      '&': {
        fontSize: '12px',
        border: '1px solid var(--border-default)',
        borderRadius: '6px',
        overflow: 'hidden',
        marginTop: '4px',
      },
      '.cm-scroller': {
        fontFamily: 'var(--font-mono, monospace)',
        lineHeight: '1.6',
        minHeight: '180px',
        maxHeight: '500px',
        overflow: 'auto',
      },
      '.cm-content': { padding: '8px 0', caretColor: 'var(--text-primary)' },
      '.cm-line': { padding: '0 12px' },
      '.cm-gutters': {
        border: 'none',
        borderRight: '1px solid var(--border-default)',
        paddingRight: '4px',
        background: 'var(--bg-panel)',
        color: 'var(--text-muted)',
      },
      '.cm-activeLineGutter': { background: 'transparent' },
      '.cm-activeLine': { background: 'rgba(255,255,255,0.03)' },
      '.cm-selectionBackground, ::selection': { background: 'rgba(92,107,192,.35) !important' },
    });

    const extensions = [basicSetup(), json(), lintGutter(), varAwareLinter, baseTheme];
    if (isDark) extensions.push(oneDark);

    let forceRedecorate = null;
    const hasTokenSupport = !!(Decoration && ViewPlugin && RangeSetBuilder && StateEffect && hoverTooltip && getVarsList);

    if (hasTokenSupport) {
      forceRedecorate = StateEffect.define();

      function buildDecorations(view) {
        const builder = new RangeSetBuilder();
        const list = getVarsList();
        if (list) {
          tokenSpansIn(view.state.doc.toString()).forEach(({ name, start, end }) => {
            const known = list.some(v => v.key === name);
            builder.add(start, end, Decoration.mark({ class: known ? 'var-tok--ok' : 'var-tok--missing' }));
          });
        }
        return builder.finish();
      }

      const tokenDecorationPlugin = ViewPlugin.fromClass(class {
        constructor(view) { this.decorations = buildDecorations(view); }
        update(u) {
          const forced = u.transactions.some(tr => tr.effects.some(e => e.is(forceRedecorate)));
          if (u.docChanged || forced) this.decorations = buildDecorations(u.view);
        }
      }, { decorations: v => v.decorations });

      const tokenHoverTooltip = hoverTooltip((view, pos) => {
        const hit = tokenSpansIn(view.state.doc.toString()).find(s => pos >= s.start && pos < s.end);
        if (!hit) return null;
        const list = getVarsList() || [];
        const entry = list.find(v => v.key === hit.name);
        return {
          pos: hit.start,
          end: hit.end,
          above: true,
          create() {
            const dom = document.createElement('div');
            dom.className = 'var-tooltip';
            dom.innerHTML = entry
              ? `<strong>{{${escapeHtml(hit.name)}}}</strong><div class="var-tooltip-value">${escapeHtml(String(entry.value ?? ''))}</div>` +
                (entry.group ? `<div class="var-tooltip-group">${escapeHtml(entry.group)}</div>` : '')
              : `<strong>{{${escapeHtml(hit.name)}}}</strong><div class="var-tooltip-missing">Not defined in environment or collection</div>`;
            return { dom };
          },
        };
      });

      extensions.push(tokenDecorationPlugin, tokenHoverTooltip);
    }

    if (onChange) {
      extensions.push(EditorView.updateListener.of(u => {
        if (u.docChanged) onChange(u.state.doc.toString());
      }));
    }

    const view = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent,
    });

    return {
      getValue: () => view.state.doc.toString(),
      setValue: (val) => {
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: val } });
      },
      refresh: () => { if (forceRedecorate) view.dispatch({ effects: forceRedecorate.of(null) }); },
      focus: () => view.focus(),
      destroy: () => view.destroy(),
    };
  } catch (e) {
    console.warn('JSON editor (CodeMirror) unavailable:', e.message);
    return null;
  }
}
