# Collection Header Redesign + Auth Tab Reorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Auth to the second tab in the request editor, and replace the cluttered collection header button row with an env selector + ⋯ dropdown (Auth/Variables open as modals; Run/Delete wire to existing functions).

**Architecture:** Two self-contained changes to vanilla JS view files. No new files. `_openDropdown` and `_openModal` are plain functions defined inside `renderCollectionsView`'s closure. Auth/Vars panels keep their existing DOM structure and auto-save behavior (PATCH on blur/change); the modal is just a new display wrapper.

**Tech Stack:** Vanilla JS, no frameworks, no bundler — edit files directly, reload Flask dev server to test.

## Global Constraints

- No new files — modify only the two listed files
- No build step — changes are live after browser hard-refresh (Ctrl+Shift+R)
- Existing auto-save behavior (PATCH on blur/change) on authPanel and varsPanel must be preserved
- All existing API calls (`window.api`, `_runCollection`, `_deleteCollection`, `_confirmDialog`) remain unchanged

---

### Task 1: Reorder Auth Tab in Request Editor

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:102`

**Interfaces:**
- Produces: SECTIONS array in new order — no downstream interface changes

- [ ] **Step 1: Change SECTIONS array**

In `request-editor-view.js` line 102, change:
```javascript
const SECTIONS = ['Params', 'Headers', 'Body', 'Auth', 'Pre-Script', 'Post-Script', 'Assertions'];
```
To:
```javascript
const SECTIONS = ['Params', 'Auth', 'Headers', 'Body', 'Pre-Script', 'Post-Script', 'Assertions'];
```

Nothing else changes — `sectionMap` already has the `'Auth'` key; tab rendering iterates SECTIONS in order.

- [ ] **Step 2: Verify in browser**

Start server: `python qaclan.py serve --port 7823`

Open the API view, select any request. Confirm the tab bar reads:
`Params | Auth | Headers | Body | Pre-Script | Post-Script | Assertions`

Click the Auth tab and confirm the auth type selector + fields render correctly.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: move Auth tab to second position in request editor"
```

---

### Task 2: Add _openDropdown and _openModal Helpers

**Files:**
- Modify: `web/static/api/views/collections-view.js`

**Interfaces:**
- Produces:
  - `_openDropdown(anchorEl, items)` — `items: Array<{label, icon?, action, danger?, divider?}>`; positions menu below anchorEl; closes on item click / Escape / outside click
  - `_openModal(title, contentEl)` — opens centered modal; detaches `contentEl` from modal DOM on close so it can be re-opened; closes on close button / Escape / outside click

- [ ] **Step 1: Insert helpers inside renderCollectionsView**

In `collections-view.js`, after the closing brace of `_loadEnvNames` (around line 17) and before `async function reload()`, insert:

```javascript
function _openDropdown(anchorEl, items) {
  document.querySelector('._col-dropdown-menu')?.remove();
  document.querySelector('._col-dropdown-overlay')?.remove();

  const overlay = document.createElement('div');
  overlay.className = '_col-dropdown-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9998;';

  const menu = document.createElement('div');
  menu.className = '_col-dropdown-menu';
  menu.style.cssText = 'position:fixed;z-index:9999;background:var(--bg-panel);border:1px solid var(--border-default);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.25);min-width:160px;padding:4px 0;';

  items.forEach(item => {
    if (item.divider) {
      const hr = document.createElement('div');
      hr.style.cssText = 'height:1px;background:var(--border-default);margin:4px 0;';
      menu.appendChild(hr);
      return;
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.style.cssText = `display:flex;align-items:center;gap:8px;width:100%;padding:7px 14px;background:none;border:none;font-size:13px;cursor:pointer;text-align:left;color:${item.danger ? 'var(--danger,#e53e3e)' : 'var(--text-default)'};`;
    btn.onmouseenter = () => { btn.style.background = 'var(--surface-2)'; };
    btn.onmouseleave = () => { btn.style.background = 'none'; };
    if (item.icon) {
      const icon = document.createElement('span');
      icon.style.cssText = 'width:16px;text-align:center;';
      icon.textContent = item.icon;
      btn.appendChild(icon);
    }
    const lbl = document.createElement('span');
    lbl.textContent = item.label;
    btn.appendChild(lbl);
    btn.onclick = (e) => { e.stopPropagation(); close(); item.action(); };
    menu.appendChild(btn);
  });

  function close() {
    menu.remove(); overlay.remove();
    document.removeEventListener('keydown', onKey);
  }
  overlay.onclick = close;
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);

  document.body.appendChild(overlay);
  document.body.appendChild(menu);

  const rect = anchorEl.getBoundingClientRect();
  menu.style.top = (rect.bottom + 4) + 'px';
  menu.style.right = (window.innerWidth - rect.right) + 'px';
}

function _openModal(title, contentEl) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;';

  const modal = document.createElement('div');
  modal.style.cssText = 'background:var(--bg-panel);border:1px solid var(--border-default);border-radius:8px;width:480px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,.4);';

  const mHead = document.createElement('div');
  mHead.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border-default);flex-shrink:0;';
  const titleEl = document.createElement('span');
  titleEl.style.cssText = 'font-size:14px;font-weight:600;';
  titleEl.textContent = title;
  const closeX = document.createElement('button');
  closeX.type = 'button';
  closeX.style.cssText = 'background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-muted);padding:0;line-height:1;';
  closeX.textContent = '×';
  mHead.appendChild(titleEl); mHead.appendChild(closeX);

  const mBody = document.createElement('div');
  mBody.style.cssText = 'padding:16px 18px;overflow-y:auto;flex:1;';
  mBody.appendChild(contentEl);

  const mFoot = document.createElement('div');
  mFoot.style.cssText = 'padding:12px 18px;border-top:1px solid var(--border-default);display:flex;justify-content:flex-end;flex-shrink:0;';
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'btn btn-sm btn-ghost';
  closeBtn.textContent = 'Close';
  mFoot.appendChild(closeBtn);

  modal.appendChild(mHead); modal.appendChild(mBody); modal.appendChild(mFoot);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  function close() {
    if (contentEl.parentNode) contentEl.parentNode.removeChild(contentEl);
    overlay.remove();
    document.removeEventListener('keydown', onKey);
  }
  closeX.onclick = close;
  closeBtn.onclick = close;
  overlay.onclick = (e) => { if (e.target === overlay) close(); };
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/api/views/collections-view.js
git commit -m "feat: add _openDropdown and _openModal helpers to collections view"
```

---

### Task 3: Redesign Collection Header Row

**Files:**
- Modify: `web/static/api/views/collections-view.js`

**Interfaces:**
- Consumes: `_openDropdown`, `_openModal` (Task 2)
- Consumes: `_runCollection(colId, colName, envName)`, `_deleteCollection(colId, colName)` (unchanged)

All changes are inside the `collections.forEach(col => { ... })` block.

- [ ] **Step 1: Remove old button variables and declarations**

Delete these lines (lines 75–102):
```javascript
// DELETE all of these:
let authExpanded = false;
const authBtn = document.createElement('button');
authBtn.className = 'btn btn-xs btn-ghost';
authBtn.textContent = 'Auth';
authBtn.title = 'Collection-level auth — inherited by requests set to "Inherit from Collection"';
rightSide.appendChild(authBtn);

let varsExpanded = false;
const varsBtn = document.createElement('button');
varsBtn.className = 'btn btn-xs btn-ghost';
varsBtn.textContent = 'Vars';
varsBtn.title = 'Collection variables — seed values for {{VAR}} set by post-scripts';
rightSide.appendChild(varsBtn);

const runBtn = document.createElement('button');
runBtn.className = 'btn btn-xs btn-ghost';
runBtn.textContent = '▶ Run';
runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name, col.env_name); };
rightSide.appendChild(runBtn);

const delBtn = document.createElement('button');
delBtn.className = 'btn btn-xs btn-ghost';
delBtn.style.color = 'var(--danger, #e53e3e)';
delBtn.textContent = '✕';
delBtn.title = 'Delete collection';
delBtn.onclick = (e) => { e.stopPropagation(); _deleteCollection(col.id, col.name); };
rightSide.appendChild(delBtn);
```

- [ ] **Step 2: Add ⋯ button after envSel append**

After line `rightSide.appendChild(envSel);` (line 72), insert:

```javascript
const menuBtn = document.createElement('button');
menuBtn.className = 'btn btn-xs btn-ghost';
menuBtn.textContent = '⋯';
menuBtn.title = 'Collection actions';
menuBtn.onclick = (e) => {
  e.stopPropagation();
  _openDropdown(menuBtn, [
    { icon: '▶', label: 'Run Collection', action: () => _runCollection(col.id, col.name, col.env_name) },
    { divider: true },
    { icon: '🔒', label: 'Auth', action: () => _openAuthModal() },
    { icon: '{}', label: 'Variables', action: () => _openVarsModal() },
    { divider: true },
    { icon: '🗑', label: 'Delete', danger: true, action: () => _deleteCollection(col.id, col.name) },
  ]);
};
rightSide.appendChild(menuBtn);
```

The `rightSide.appendChild(expandBtn)` line (currently line 107) stays — it comes after menuBtn, giving the order: `envSel → menuBtn → expandBtn`.

- [ ] **Step 3: Update header.onclick guard**

Change (lines 122–125):
```javascript
header.onclick = (e) => {
  if (e.target === runBtn || e.target === expandBtn || e.target === varsBtn || e.target === authBtn || e.target === envSel) return;
  _toggleExpand();
};
```
To:
```javascript
header.onclick = (e) => {
  if (e.target === expandBtn || e.target === menuBtn || e.target === envSel) return;
  _toggleExpand();
};
```

- [ ] **Step 4: Replace _toggleAuthPanel with _openAuthModal**

Find and delete the `_toggleAuthPanel` function and its `authBtn.onclick` binding (lines 230–235):
```javascript
// DELETE:
async function _toggleAuthPanel() {
  authExpanded = !authExpanded;
  authPanel.style.display = authExpanded ? '' : 'none';
  authBtn.classList.toggle('active', authExpanded);
}
authBtn.onclick = (e) => { e.stopPropagation(); _toggleAuthPanel(); };
```

In their place, add:
```javascript
function _openAuthModal() {
  authPanel.style.cssText = 'display:flex;flex-direction:column;gap:10px;';
  _openModal('Collection Auth', authPanel);
}
```

Also change the authPanel's initial cssText (line 130) from:
```javascript
authPanel.style.cssText = 'display:none;padding:10px 14px 8px;border-bottom:1px solid var(--border-default);';
```
To:
```javascript
authPanel.style.cssText = 'display:none;';
```
(Padding and border are no longer needed — the modal provides its own padding.)

- [ ] **Step 5: Replace _toggleVarsPanel with _openVarsModal**

Find and delete the `_toggleVarsPanel` function and `varsBtn.onclick` binding (lines 311–321):
```javascript
// DELETE:
let _colVarsLoaded = false;
async function _toggleVarsPanel() {
  varsExpanded = !varsExpanded;
  varsPanel.style.display = varsExpanded ? '' : 'none';
  varsBtn.classList.toggle('active', varsExpanded);
  if (varsExpanded && !_colVarsLoaded) {
    _colVarsLoaded = true;
    const res = await window.api('GET', `/collections/${col.id}/vars`);
    (res.vars || []).forEach(v => _addVarRow(v));
  }
}
varsBtn.onclick = (e) => { e.stopPropagation(); _toggleVarsPanel(); };
```

In their place, add:
```javascript
let _colVarsLoaded = false;
async function _openVarsModal() {
  if (!_colVarsLoaded) {
    _colVarsLoaded = true;
    const res = await window.api('GET', `/collections/${col.id}/vars`);
    (res.vars || []).forEach(v => _addVarRow(v));
  }
  varsPanel.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
  _openModal('Collection Variables', varsPanel);
}
```

Also change varsPanel's initial cssText (line 241) from:
```javascript
varsPanel.style.cssText = 'display:none;padding:8px 14px 6px;border-bottom:1px solid var(--border);';
```
To:
```javascript
varsPanel.style.cssText = 'display:none;';
```

- [ ] **Step 6: Remove inline panel appends from section**

Delete these two lines:
```javascript
section.appendChild(authPanel);   // ~line 237
section.appendChild(varsPanel);   // ~line 323
```

The panels now live only inside modals — they must not be in the section DOM.

- [ ] **Step 7: Verify in browser**

Start server: `python qaclan.py serve --port 7823` then hard-refresh (Ctrl+Shift+R).

Test checklist:
- [ ] Collection header shows: `[Collection Name] [N requests]` on left; `[env dropdown] [⋯] [▾]` on right
- [ ] Clicking ⋯ opens dropdown with: Run Collection / divider / Auth / Variables / divider / Delete
- [ ] Clicking outside dropdown or pressing Escape closes it
- [ ] Clicking "Run Collection" triggers run confirm dialog (same behavior as before)
- [ ] Clicking "Auth" opens "Collection Auth" modal with auth type selector + dynamic fields
- [ ] Changing auth type in modal auto-saves (network PATCH fires immediately on change)
- [ ] Closing and re-opening Auth modal shows the last-saved state
- [ ] Clicking "Variables" opens "Collection Variables" modal with vars table
- [ ] Adding/editing a var and tabbing away auto-saves (PATCH fires on blur)
- [ ] Re-opening Variables modal shows the current vars (not reset)
- [ ] Clicking "Delete" shows confirm dialog; confirming deletes and reloads list
- [ ] Clicking outside modal or pressing Escape closes modal
- [ ] Clicking collection name/row still toggles expand/collapse
- [ ] Env selector still PATCHes env on change

- [ ] **Step 8: Commit**

```bash
git add web/static/api/views/collections-view.js
git commit -m "feat: replace collection header buttons with ⋯ dropdown and modals"
```
