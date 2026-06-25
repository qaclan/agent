/**
 * createJsonEditor({ parent, value, isDark, onChange }) → Promise<editor|null>
 * Uses the bundled CM6 from window.CM6 (vendor/codemirror/cm6.js).
 * Returns null if CM6 unavailable.
 * editor: { getValue(), setValue(str), focus(), destroy() }
 */

export async function createJsonEditor({ parent, value = '', isDark = true, onChange }) {
  try {
    const CM = window.CM6;
    if (!CM) throw new Error('CM6 vendor bundle not loaded');

    const { EditorView, EditorState, basicSetup, json, jsonParseLinter, linter, lintGutter, oneDark } = CM;

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
      focus: () => view.focus(),
      destroy: () => view.destroy(),
    };
  } catch (e) {
    console.warn('JSON editor (CodeMirror) unavailable:', e.message);
    return null;
  }
}
