# Rebuilding cm6.js

This file is a pre-built, minified IIFE bundle of CodeMirror 6 + language packs
(Python, JavaScript) + one-dark theme. It exposes everything on `window.CM6` so
the agent's non-module `app.js` can consume it via a plain `<script>` tag.

**You don't need to rebuild it unless you want to upgrade CM6 versions.**
The file is committed to the repo and bundled into the Nuitka binary via
`--include-data-dir=web/static=web/static` (see `build.sh`).

## When to rebuild

- You want a newer CM6 version
- You want to add/remove a language pack (e.g. add TypeScript, remove JS)
- You want to add an extension (autocomplete, lint, etc.)

## Requirements

- Node 18+ (Node 20 recommended — use `nvm use 20` if you have nvm)
- npm

## Steps

```bash
# 1. Work in a throwaway dir outside the repo
mkdir -p /tmp/cm6-bundle && cd /tmp/cm6-bundle

# 2. Init and install packages (pin to major 6)
cat > package.json << 'EOF'
{ "name": "cm6-bundle", "version": "1.0.0", "private": true }
EOF

npm install --silent --no-audit --no-fund \
  @codemirror/state@6 \
  @codemirror/view@6 \
  @codemirror/commands@6 \
  @codemirror/language@6 \
  @codemirror/search@6 \
  @codemirror/autocomplete@6 \
  @codemirror/lang-python@6 \
  @codemirror/lang-javascript@6 \
  @codemirror/lang-json@6 \
  @codemirror/lint@6 \
  @codemirror/theme-one-dark@6 \
  @lezer/highlight@1 \
  graphql@16 \
  cm6-graphql@0.2 \
  esbuild@0.24

# 3. Write entry.js (see snippet below)
# 4. Bundle
./node_modules/.bin/esbuild entry.js \
  --bundle --format=iife --minify --target=es2019 \
  --outfile=cm6.js

# 5. Copy the result back into the repo
cp cm6.js /path/to/repo/web/static/vendor/codemirror/cm6.js

# 6. Clean up
cd && rm -rf /tmp/cm6-bundle
```

## entry.js

This is the actual entry point used to produce the committed `cm6.js` —
keep it in sync with reality (json language + lint support, the
decoration/hover-tooltip primitives used for {{var}} highlighting, and the
autocomplete primitives used for {{var}} suggestions in the raw JSON body
editor, and the schema-less GraphQL language pack used by the GraphQL
query/variables body editor) so a future rebuild doesn't silently drop
functionality.

```js
import { EditorState, Compartment, RangeSetBuilder, StateEffect } from "@codemirror/state"
import {
  EditorView, keymap, lineNumbers, highlightActiveLine,
  highlightActiveLineGutter, drawSelection,
  Decoration, ViewPlugin, ViewUpdate, hoverTooltip,
} from "@codemirror/view"
import {
  defaultKeymap, indentWithTab, history, historyKeymap,
} from "@codemirror/commands"
import {
  indentOnInput, bracketMatching, syntaxHighlighting,
  defaultHighlightStyle, foldGutter, foldKeymap, indentUnit,
} from "@codemirror/language"
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search"
import { autocompletion, completionKeymap, CompletionContext } from "@codemirror/autocomplete"
import { python } from "@codemirror/lang-python"
import { javascript } from "@codemirror/lang-javascript"
import { json, jsonParseLinter } from "@codemirror/lang-json"
import { linter, lintGutter } from "@codemirror/lint"
import { oneDark } from "@codemirror/theme-one-dark"
import { graphql } from "cm6-graphql"

// basicSetup() is shared by every CM6 editor in the app (JSON body editor +
// the Playwright script recorder editor in app.js). Keep it unchanged when
// adding new capabilities — opt individual editors into new extensions
// (e.g. autocompletion()) at their own call site instead.
function basicSetup() {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightActiveLine(),
    foldGutter(),
    drawSelection(),
    history(),
    indentUnit.of("    "),  // 4-space indent (Python convention)
    indentOnInput(),
    bracketMatching(),
    syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    highlightSelectionMatches(),
    keymap.of([
      ...defaultKeymap,
      ...historyKeymap,
      ...foldKeymap,
      ...searchKeymap,
      indentWithTab,
    ]),
  ]
}

window.CM6 = {
  EditorState, Compartment, RangeSetBuilder, StateEffect,
  EditorView, Decoration, ViewPlugin, ViewUpdate, hoverTooltip, keymap,
  basicSetup, oneDark, indentUnit,
  python, javascript, json, jsonParseLinter, linter, lintGutter,
  autocompletion, completionKeymap, CompletionContext,
  graphql,
}
```

## Notes

- End users never run this. They get `cm6.js` bundled inside the Nuitka binary.
- Target is `es2019` so it runs in any modern browser without transpilation surprises.
- Bundle is ~730 KB minified (includes Python + JS grammars, GraphQL grammar + graphql-js, one-dark theme, autocomplete).
