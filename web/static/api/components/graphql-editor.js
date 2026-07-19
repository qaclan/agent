/**
 * createGraphqlEditor({ parent, value, isDark, onChange, getVarsList }) → Promise<editor|null>
 * Uses the bundled CM6 GraphQL language pack from window.CM6 (vendor/codemirror/cm6.js).
 * Returns null if CM6 or the graphql() extension is unavailable — caller falls
 * back to a plain textarea, same pattern as createJsonEditor.
 * Schema-less: no introspection/schema wired in, so this gives syntax
 * highlighting, bracket matching, and GraphQL-grammar completion only — no
 * field/type-aware autocomplete (that needs a loaded schema, out of scope).
 * editor: { getValue(), setValue(str), refresh(), focus(), destroy() }
 */
import { tokenSpansIn, escapeHtml } from './var-style.js';

/**
 * Pretty-prints a GraphQL document (one-liner or minified) into indented
 * multi-line form. Brace-depth based, not a full GraphQL parser: braces
 * inside parens (input object arguments, e.g. `filter: { name: $name }`)
 * are kept inline since they're argument values, not selection sets.
 */
export function formatGraphQL(src) {
  if (typeof src !== 'string') return src;
  const trimmed = src.trim();
  if (!trimmed) return src;
  const tokens = trimmed.match(/"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|[{}()]|[^{}()"]+/g) || [];
  const IND = '  ';
  let indent = 0;
  let parenDepth = 0;
  let out = '';
  let atLineStart = true;

  const trimTrailingSpace = () => { out = out.replace(/[ \t]+$/, ''); };
  const newLine = () => {
    trimTrailingSpace();
    if (!out.endsWith('\n')) out += '\n';
    atLineStart = true;
  };
  const appendInline = (text) => {
    if (atLineStart) {
      text = text.replace(/^ +/, '');
      if (!text) return;
      out += IND.repeat(indent) + text;
      atLineStart = false;
    } else {
      out += text;
    }
  };

  for (const tok of tokens) {
    if (tok === '(') { parenDepth++; appendInline(tok); continue; }
    if (tok === ')') { parenDepth = Math.max(0, parenDepth - 1); appendInline(tok); continue; }
    if (tok === '{' && parenDepth === 0) {
      trimTrailingSpace();
      out += (out.length ? ' {\n' : '{\n');
      indent++;
      atLineStart = true;
      continue;
    }
    if (tok === '}' && parenDepth === 0) {
      indent = Math.max(0, indent - 1);
      newLine();
      out += IND.repeat(indent) + '}\n';
      atLineStart = true;
      continue;
    }
    if (tok === '{' || tok === '}') { appendInline(tok); continue; }

    if (parenDepth === 0 && indent > 0) {
      const words = tok.trim().split(/\s+/).filter(Boolean);
      words.forEach((w, i) => {
        if (i > 0) newLine();
        appendInline(w);
      });
    } else {
      appendInline(tok.replace(/\s+/g, ' '));
    }
  }
  return out.replace(/\s+$/, '') + '\n';
}

export async function createGraphqlEditor({ parent, value = '', isDark = true, onChange, getVarsList }) {
  try {
    const CM = window.CM6;
    if (!CM || !CM.graphql) throw new Error('CM6 GraphQL language pack not loaded');

    const { EditorView, EditorState, basicSetup, graphql, oneDark } = CM;
    const { Decoration, ViewPlugin, RangeSetBuilder, StateEffect, hoverTooltip } = CM;
    const { autocompletion, completionKeymap, keymap } = CM;

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
        minHeight: '140px',
        maxHeight: '400px',
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

    const extensions = [basicSetup(), graphql(), baseTheme];
    if (isDark) extensions.push(oneDark);

    // {{var}} name suggestions while typing — identical mechanism to the raw
    // JSON body editor's var autocomplete, just wired into the GraphQL doc.
    if (autocompletion && getVarsList) {
      function varCompletions(context) {
        const word = context.matchBefore(/\{\{[\w.-]*/);
        if (!word) return null;
        const list = getVarsList() || [];
        if (!list.length) return null;
        return {
          from: word.from + 2,
          options: list.map(v => ({
            label: v.key,
            type: 'variable',
            detail: v.group || undefined,
            info: () => document.createTextNode(String(v.value ?? '')),
            apply: (view, completion, from, to) => {
              const alreadyClosed = view.state.sliceDoc(to, to + 2) === '}}';
              const insert = completion.label + (alreadyClosed ? '' : '}}');
              view.dispatch({
                changes: { from, to, insert },
                selection: { anchor: from + insert.length },
              });
            },
          })),
          validFor: /^[\w.-]*$/,
        };
      }
      extensions.push(autocompletion({ override: [varCompletions] }));
      if (keymap && completionKeymap) extensions.push(keymap.of(completionKeymap));
    }

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
      state: EditorState.create({ doc: formatGraphQL(value), extensions }),
      parent,
    });

    return {
      getValue: () => view.state.doc.toString(),
      setValue: (val) => {
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: formatGraphQL(val) } });
      },
      refresh: () => { if (forceRedecorate) view.dispatch({ effects: forceRedecorate.of(null) }); },
      focus: () => view.focus(),
      destroy: () => view.destroy(),
    };
  } catch (e) {
    console.warn('GraphQL editor (CodeMirror) unavailable:', e.message);
    return null;
  }
}
