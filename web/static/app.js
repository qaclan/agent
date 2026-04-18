// ── CM6 load check (diagnostic) ────────────────────────────────
// Flip to `true` if you ever need to silence this.
if (typeof window !== 'undefined') {
  if (window.CM6 && window.CM6.EditorView) {
    console.log('[qaclan] CodeMirror 6 loaded:', Object.keys(window.CM6))
  } else {
    console.warn('[qaclan] CodeMirror 6 NOT loaded — window.CM6 is undefined')
  }
}

// ── Script Editor Wrapper ──────────────────────────────────────
// Unified interface so modal code doesn't care whether the underlying editor
// is CodeMirror 6 or a plain textarea. Every instance exposes the same shape:
//   { mode, getValue, setValue, insertAtCursor, focus, destroy }
//
// Resolution order:
//   1. state.settings.editor_mode === 'code' AND window.CM6 loaded → CM6
//   2. CM6 init threw → textarea fallback + toast
//   3. state.settings.editor_mode === 'text' → textarea

function _createScriptEditor(hostEl, initialContent, { readOnly = false } = {}) {
  const wantCode = (state.settings.editor_mode || 'code') === 'code'
  if (wantCode && window.CM6 && window.CM6.EditorView) {
    try {
      return _createCM6ScriptEditor(hostEl, initialContent || '', { readOnly })
    } catch (e) {
      console.warn('[qaclan] CM6 init failed, falling back to textarea:', e)
      toast('Code editor unavailable, using plain text', 'warning')
    }
  }
  return _createTextareaScriptEditor(hostEl, initialContent || '', { readOnly })
}

function _createCM6ScriptEditor(hostEl, initialContent, { readOnly }) {
  const { EditorState, EditorView, basicSetup, python, oneDark } = window.CM6
  const extensions = [basicSetup(), python(), oneDark]
  if (readOnly) extensions.push(EditorView.editable.of(false))
  // Host styling: border, rounded, themed to match the rest of the UI
  hostEl.style.border = '1px solid var(--border-default)'
  hostEl.style.borderRadius = '6px'
  hostEl.style.overflow = 'hidden'
  hostEl.style.minHeight = '55vh'
  hostEl.style.maxHeight = '65vh'
  hostEl.style.display = 'flex'
  hostEl.style.flexDirection = 'column'
  const view = new EditorView({
    state: EditorState.create({ doc: initialContent, extensions }),
    parent: hostEl,
  })
  // Let CM6's scroller fill the host
  const scroller = hostEl.querySelector('.cm-editor')
  if (scroller) {
    scroller.style.flex = '1 1 auto'
    scroller.style.minHeight = '0'
    scroller.style.height = '100%'
  }
  return {
    mode: 'code',
    getValue: () => view.state.doc.toString(),
    setValue: (text) => {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text || '' },
      })
    },
    insertAtCursor: (text) => {
      const { from, to } = view.state.selection.main
      view.dispatch({
        changes: { from, to, insert: text },
        selection: { anchor: from + text.length },
        scrollIntoView: true,
      })
      view.focus()
    },
    focus: () => view.focus(),
    destroy: () => { try { view.destroy() } catch (_) {} },
  }
}

function _createTextareaScriptEditor(hostEl, initialContent, { readOnly }) {
  const ta = document.createElement('textarea')
  ta.style.cssText = 'width:100%;min-height:55vh;max-height:65vh;font-family:monospace;font-size:12px;line-height:1.5;padding:10px;background:var(--bg-base);color:var(--text-primary);border:1px solid var(--border-default);border-radius:6px;resize:vertical'
  if (readOnly) {
    ta.readOnly = true
    ta.style.cursor = 'default'
  }
  ta.value = initialContent
  hostEl.appendChild(ta)
  return {
    mode: 'text',
    getValue: () => ta.value,
    setValue: (text) => { ta.value = text || '' },
    insertAtCursor: (text) => {
      const start = ta.selectionStart
      const end = ta.selectionEnd
      ta.value = ta.value.slice(0, start) + text + ta.value.slice(end)
      const newPos = start + text.length
      ta.focus()
      ta.setSelectionRange(newPos, newPos)
      _scrollTextareaToCaret(ta, newPos)
      _flashTextareaBackground(ta)
    },
    focus: () => ta.focus(),
    destroy: () => {},
  }
}

// Call from DevTools console as `qcEditorSmokeTest()` to spawn a test CM6 editor
// in the current page. Leaves a bordered panel at the top-left. Useful for
// verifying the bundle renders before wiring it into real modals.
function qcEditorSmokeTest() {
  if (!window.CM6) { console.error('window.CM6 not loaded'); return }
  const { EditorState, EditorView, basicSetup, python, oneDark } = window.CM6
  const host = document.createElement('div')
  host.id = 'qc-editor-smoketest'
  host.style.cssText = 'position:fixed;top:20px;left:20px;width:600px;height:300px;z-index:9999;border:2px solid #3b82f6;background:var(--bg-base);resize:both;overflow:auto'
  const closeBtn = document.createElement('button')
  closeBtn.textContent = '✕ close test'
  closeBtn.style.cssText = 'position:absolute;top:4px;right:4px;z-index:10000;font-size:11px;padding:2px 6px'
  closeBtn.onclick = () => host.remove()
  host.appendChild(closeBtn)
  document.body.appendChild(host)
  new EditorView({
    state: EditorState.create({
      doc: '# CM6 smoke test\nfrom playwright.sync_api import sync_playwright\n\nwith sync_playwright() as p:\n    browser = p.chromium.launch()\n    page = browser.new_page()\n    page.goto("https://example.com")\n    print(page.title())\n',
      extensions: [basicSetup(), python(), oneDark],
    }),
    parent: host,
  })
  console.log('[qaclan] smoke test editor rendered — drag corner to resize, click ✕ to close')
}

// ── State & Router ──────────────────────────────────────────────

const state = {
  activeProject: null,
  page: 'scripts',
  authenticated: false,
  user: null,
  settings: { editor_mode: 'code' },  // backend overrides via /api/settings on init
}

const routes = {
  features: renderFeaturesPage,
  scripts:  renderScriptsPage,
  suites:   renderSuitesPage,
  runs:     renderRunsPage,
  envs:     renderEnvsPage,
  settings: renderSettingsPage,
}

async function navigate(page) {
  state.page = page
  renderSidebar()
  renderTopbar()
  const el = document.getElementById('page-content')
  el.className = 'page-animate'
  await routes[page]()
}

async function init() {
  // Check auth status first
  const authRes = await api('GET', '/auth/status')
  if (!authRes.authenticated) {
    renderAuthScreen()
    return
  }
  state.authenticated = true
  state.user = authRes.user || null

  // Load backend-driven settings (editor mode, etc.) — best-effort
  try {
    const settingsRes = await api('GET', '/settings')
    if (settingsRes && settingsRes.ok && settingsRes.settings) {
      Object.assign(state.settings, settingsRes.settings)
    }
  } catch (e) { /* keep defaults */ }

  const res = await api('GET', '/projects/active')
  if (res.id) state.activeProject = { id: res.id, name: res.name }
  renderSidebar()
  renderTopbar()
  await routes[state.page]()

  // Close dropdowns on outside click — use a named function so it's only registered once
  if (!window._qcDropdownListenerAdded) {
    window._qcDropdownListenerAdded = true
    document.addEventListener('click', (e) => {
      const wrap = document.getElementById('project-switcher-wrap')
      if (wrap && !wrap.contains(e.target)) {
        const dd = document.getElementById('project-dropdown')
        if (dd) dd.classList.add('hidden')
      }
    })
  }
}

document.addEventListener('DOMContentLoaded', init)

// ── API Helper ──────────────────────────────────────────────────

async function api(method, path, body = null) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } }
    if (body) opts.body = JSON.stringify(body)
    const res = await fetch('/api' + path, opts)
    const data = await res.json()
    return data
  } catch (e) {
    return { ok: false, error: e.message }
  }
}

// ── SVG Icons ───────────────────────────────────────────────────

function iconEnv() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><circle cx="7.5" cy="7.5" r="3"/><path d="M7.5 1v2M7.5 12v2M1 7.5h2M12 7.5h2M3.1 3.1l1.4 1.4M10.5 10.5l1.4 1.4M3.1 11.9l1.4-1.4M10.5 4.5l1.4-1.4"/></svg>'
}
function iconDiscover() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M7.5 1l1.8 4.2L14 7.5l-4.7 2.3L7.5 14l-1.8-4.2L1 7.5l4.7-2.3z"/></svg>'
}
function iconTestcase() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><rect x="2" y="1.5" width="11" height="12" rx="1.5"/><path d="M5 5.5l1.5 1.5L9 4.5M5 9.5h5"/></svg>'
}
function iconLocator() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M2 2l5 11 1.5-4.5L13 7z"/><path d="M9.5 9.5l3 3"/></svg>'
}
function iconScript() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M4.5 4l-3 3.5 3 3.5M10.5 4l3 3.5-3 3.5M6.5 12.5l2-10"/></svg>'
}
function iconSuite() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><rect x="2" y="1" width="11" height="4" rx="1"/><rect x="2" y="6" width="11" height="4" rx="1"/><rect x="2" y="11" width="11" height="3" rx="1"/></svg>'
}
function iconRun() {
  return '<svg viewBox="0 0 15 15" fill="currentColor"><path d="M4 2.5v10l8.5-5z"/></svg>'
}

// ── Sidebar ─────────────────────────────────────────────────────

function renderSidebar() {
  const logo = document.getElementById('sidebar-logo')
  logo.innerHTML = `
    <div class="logo-wrap">
      <img class="logo-icon" src="logo.png" alt="QAClan">
      <div class="logo-tag">community</div>
    </div>`

  const nav = document.getElementById('sidebar-nav')
  const p = state.page
  nav.innerHTML = `
    <div class="nav-section">
      <div class="nav-item ${p==='envs'?'active':''}" onclick="navigate('envs')">
        ${iconEnv()} Environment
      </div>
    </div>
    <div class="nav-section">
      <div class="nav-label">Testing</div>
      <div class="nav-item sub ${p==='features'?'active':''}" onclick="navigate('features')">
        ${iconTestcase()} Features
      </div>
      <div class="nav-item sub ${p==='scripts'?'active':''}" onclick="navigate('scripts')">
        ${iconScript()} Scripts
      </div>
      <div class="nav-item sub ${p==='suites'?'active':''}" onclick="navigate('suites')">
        ${iconSuite()} Suites
      </div>
      <div class="nav-item sub ${p==='runs'?'active':''}" onclick="navigate('runs')">
        ${iconRun()} Runs
      </div>
    </div>
    <div class="nav-section nav-section-bottom">
      <div class="nav-item ${p==='settings'?'active':''}" onclick="navigate('settings')">
        ${iconSettings()} Settings
      </div>
    </div>`
}

// ── Top Bar ─────────────────────────────────────────────────────

async function renderTopbar() {
  const bar = document.getElementById('topbar')
  const titles = {
    features: ['Features', 'Manage web features'],
    scripts:  ['Scripts', 'Manage automation scripts'],
    suites:   ['Suites', 'Manage regression suites'],
    runs:     ['Regression Runs', 'View execution history'],
    envs:     ['Environments', 'Manage environment variables'],
    settings: ['Settings', 'Manage auth key and preferences'],
  }
  const [title, sub] = titles[state.page] || ['QAClan', '']
  const allProjects = await api('GET', '/projects')
  const projects = allProjects.projects || []

  bar.innerHTML = `
    <div class="topbar-left">
      <h1>${title}</h1>
      <p>${sub}</p>
    </div>
    <div class="topbar-right">
      <button class="theme-btn" id="btn-theme" onclick="toggleTheme()" title="Toggle light/dark mode">
        ${getTheme() === 'light' ? '\u263D' : '\u2600'}
      </button>
      <button class="sync-btn" id="btn-pull" onclick="triggerPull()" title="Pull workspace from cloud">
        <span class="sync-icon">\u2193</span>
        <span class="sync-label">Pull</span>
      </button>
      <button class="sync-btn" id="btn-push" onclick="triggerPush()" title="Push pending changes to cloud">
        <span class="sync-icon">\u2191</span>
        <span class="sync-label">Push</span>
      </button>
      <div class="project-switcher" id="project-switcher-wrap">
        <button class="project-switcher-btn" onclick="toggleProjectDropdown(event)">
          <span class="project-dot"></span>
          <span>${state.activeProject ? escHtml(state.activeProject.name) : 'Select Project'}</span>
          <span class="project-chevron">\u25BE</span>
        </button>
        <div class="project-dropdown hidden" id="project-dropdown">
          ${projects.map(p => `
            <div class="project-dropdown-item ${state.activeProject?.id===p.id?'active':''}"
                 onclick="switchProject('${p.id}')">
              <span>${state.activeProject?.id===p.id ? '\u25CF ' : '\u25CB '} ${escHtml(p.name)}</span>
              <span class="project-delete-btn" onclick="event.stopPropagation();deleteProjectPrompt('${p.id}','${escHtml(p.name)}')" title="Delete">\u2715</span>
            </div>`).join('')}
          <div class="project-dropdown-divider"></div>
          <div class="project-dropdown-item project-dropdown-new" onclick="createProjectPrompt()">
            + New Project
          </div>
        </div>
      </div>
    </div>`
}

function getTheme() {
  return localStorage.getItem('qaclan-theme') || 'dark'
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('qaclan-theme', theme)
  const btn = document.getElementById('btn-theme')
  if (btn) btn.textContent = theme === 'light' ? '\u263D' : '\u2600'
}
function toggleTheme() {
  applyTheme(getTheme() === 'light' ? 'dark' : 'light')
}
// Apply immediately so first paint matches the saved theme
applyTheme(getTheme())

async function triggerPush() {
  const btn = document.getElementById('btn-push')
  if (!btn || btn.disabled) return
  btn.disabled = true
  btn.classList.add('syncing')
  try {
    const res = await api('POST', '/sync/push')
    if (res.ok === false) { toast(res.error || 'Push failed', 'error'); return }
    toast(res.message || 'Pushed', res.remaining > 0 ? 'info' : 'success')
  } catch (e) {
    toast('Push failed: ' + e, 'error')
  } finally {
    btn.disabled = false
    btn.classList.remove('syncing')
  }
}

async function triggerPull() {
  const btn = document.getElementById('btn-pull')
  if (!btn || btn.disabled) return
  btn.disabled = true
  btn.classList.add('syncing')
  try {
    const res = await api('POST', '/sync/pull')
    if (res.ok === false) { toast(res.error || 'Pull failed', 'error'); return }
    toast(res.message || 'Pulled', 'success')
    await renderTopbar()
    if (routes[state.page]) await routes[state.page]()
  } catch (e) {
    toast('Pull failed: ' + e, 'error')
  } finally {
    btn.disabled = false
    btn.classList.remove('syncing')
  }
}

function toggleProjectDropdown(e) {
  e.stopPropagation()
  document.getElementById('project-dropdown').classList.toggle('hidden')
}

async function switchProject(id) {
  const res = await api('POST', '/projects/active', { id })
  if (res.ok === false) { toast(res.error, 'error'); return }
  state.activeProject = { id: res.id, name: res.name }
  document.getElementById('project-dropdown').classList.add('hidden')
  await renderTopbar()
  await routes[state.page]()
}

async function deleteProjectPrompt(id, name) {
  document.getElementById('project-dropdown').classList.add('hidden')
  showModal('Delete Project', `
    <p>Delete project <strong>"${name}"</strong> and all its data?</p>
    <p class="text-muted mt-4">This will remove all features, scripts, suites, environments, and run history. This action cannot be undone.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Delete', cls: 'btn-danger', action: async () => {
      const res = await api('DELETE', '/projects/' + id)
      if (res.ok === false) { toast(res.error, 'error'); return }
      if (state.activeProject?.id === id) {
        state.activeProject = null
      }
      closeModal()
      renderTopbar()
      await routes[state.page]()
      toast('Project deleted')
    }}
  ])
}

async function createProjectPrompt() {
  document.getElementById('project-dropdown').classList.add('hidden')
  showModal('New Project', `
    <div class="form-group">
      <label class="form-label">Project Name</label>
      <input type="text" id="new-project-name" placeholder="e.g. MyApp" autofocus>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Create', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('new-project-name').value.trim()
      if (!name) return
      const res = await api('POST', '/projects', { name })
      if (res.ok === false) { toast(res.error, 'error'); return }
      state.activeProject = { id: res.id, name: res.name }
      closeModal()
      renderTopbar()
      await routes[state.page]()
      toast('Project "' + name + '" created')
    }}
  ])
}

// ── Modal System ────────────────────────────────────────────────

function showModal(title, bodyHTML, buttons = [], subtitle = '', size = '') {
  const backdrop = document.getElementById('modal-backdrop')
  const root = document.getElementById('modal-root')

  const btns = buttons.map((b, i) =>
    `<button class="btn btn-sm ${b.cls}" data-btn-idx="${i}">${escHtml(b.label)}</button>`
  ).join('')

  const sizeClass = size ? ` modal-${size}` : ''
  root.innerHTML = `
    <div class="modal-card${sizeClass}">
      <div class="modal-header">
        <div>
          <div class="modal-title">${title}</div>
          ${subtitle ? `<div class="modal-subtitle">${subtitle}</div>` : ''}
        </div>
        <button class="modal-close" onclick="closeModal()">\u2715</button>
      </div>
      <div class="modal-body">${bodyHTML}</div>
      ${buttons.length ? `<div class="modal-footer">${btns}</div>` : ''}
    </div>`

  backdrop.classList.remove('hidden')
  root.classList.remove('hidden')

  buttons.forEach((b, i) => {
    root.querySelector(`[data-btn-idx="${i}"]`)
        ?.addEventListener('click', b.action)
  })

  backdrop.onclick = closeModal
  setTimeout(() => root.querySelector('input, textarea, select')?.focus(), 50)
}

function closeModal() {
  // Fire any cleanup hook the current modal registered (e.g. CM6 editor teardown)
  // before we blow away the modal DOM. Runs once, then clears.
  const hook = window._qcModalCleanupHook
  window._qcModalCleanupHook = null
  if (typeof hook === 'function') {
    try { hook() } catch (e) { console.warn('[qaclan] modal cleanup hook failed:', e) }
  }

  document.getElementById('modal-backdrop').classList.add('hidden')
  document.getElementById('modal-root').classList.add('hidden')
  document.getElementById('modal-root').innerHTML = ''
  document.getElementById('modal-backdrop').onclick = null
}

// Overlay modal: renders into a dynamically-created container ABOVE the primary
// modal, so nested modals (e.g. Scan & Bind review from inside the edit modal)
// don't destroy the underlying modal's DOM and state.
function showOverlayModal(title, bodyHTML, buttons = [], subtitle = '', size = '') {
  closeOverlayModal()  // ensure any prior overlay is gone

  const backdrop = document.createElement('div')
  backdrop.id = 'modal-overlay-backdrop'
  backdrop.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:200;backdrop-filter:blur(2px)'
  document.body.appendChild(backdrop)

  const root = document.createElement('div')
  root.id = 'modal-overlay-root'
  root.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:201;min-width:480px;width:90%;display:flex;flex-direction:column;animation:modalIn 0.18s ease'
  if (size === 'xl') {
    root.style.maxWidth = '1280px'
    root.style.maxHeight = '92vh'
  } else if (size === 'lg') {
    root.style.maxWidth = '960px'
    root.style.maxHeight = '92vh'
  } else {
    root.style.maxWidth = '620px'
    root.style.maxHeight = '85vh'
  }
  document.body.appendChild(root)

  const btns = buttons.map((b, i) =>
    `<button class="btn btn-sm ${b.cls}" data-btn-idx="${i}">${escHtml(b.label)}</button>`
  ).join('')

  const sizeClass = size ? ` modal-${size}` : ''
  root.innerHTML = `
    <div class="modal-card${sizeClass}">
      <div class="modal-header">
        <div>
          <div class="modal-title">${title}</div>
          ${subtitle ? `<div class="modal-subtitle">${subtitle}</div>` : ''}
        </div>
        <button class="modal-close" onclick="closeOverlayModal()">\u2715</button>
      </div>
      <div class="modal-body">${bodyHTML}</div>
      ${buttons.length ? `<div class="modal-footer">${btns}</div>` : ''}
    </div>`

  buttons.forEach((b, i) => {
    root.querySelector(`[data-btn-idx="${i}"]`)
        ?.addEventListener('click', b.action)
  })

  backdrop.onclick = closeOverlayModal
  setTimeout(() => root.querySelector('input, textarea, select')?.focus(), 50)
}

function closeOverlayModal() {
  document.getElementById('modal-overlay-backdrop')?.remove()
  document.getElementById('modal-overlay-root')?.remove()
}

// ── Toast Notifications ─────────────────────────────────────────

function toast(message, type = 'success') {
  const container = document.getElementById('toast-root')
  const el = document.createElement('div')
  el.className = `toast toast-${type}`
  el.innerHTML = `<span class="toast-icon"></span><span>${escHtml(message)}</span>`
  container.appendChild(el)
  setTimeout(() => {
    el.style.animation = 'toastOut 0.2s ease forwards'
    setTimeout(() => el.remove(), 200)
  }, 3000)
}

// ── No Project State ────────────────────────────────────────────

function renderNoProject(page) {
  page.innerHTML = `
    <div class="loading-state">
      <div class="empty-state-icon" style="font-size:40px">\u25C8</div>
      <p style="font-size:15px;font-weight:500;color:var(--text-primary)">No project selected</p>
      <p class="text-muted">Use the project switcher in the top right to create or select a project.</p>
    </div>`
}

// ── Utilities ───────────────────────────────────────────────────

function escHtml(str) {
  return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')
}

function fmtDate(iso) {
  if (!iso) return '\u2014'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Auth Screen (shown when not logged in) ─────────────────────

function renderAuthScreen() {
  const app = document.getElementById('app')
  app.style.display = 'none'

  let screen = document.getElementById('auth-screen')
  if (!screen) {
    screen = document.createElement('div')
    screen.id = 'auth-screen'
    document.body.appendChild(screen)
  }

  screen.innerHTML = `
    <div class="auth-card">
      <div class="auth-logo">
        <img src="logo.png" alt="QAClan" style="width:48px;height:48px;border-radius:12px">
        <h1 style="font-size:22px;font-weight:600;color:var(--text-primary);margin-top:12px">QAClan</h1>
        <p class="text-muted" style="margin-top:4px;font-size:13px">Enter your auth key to continue</p>
      </div>
      <div class="form-group" style="margin-top:24px">
        <label class="form-label">Auth Key</label>
        <input type="password" id="auth-key-input" placeholder="qc_..." style="width:100%">
        <p class="text-muted" style="margin-top:6px;font-size:11px">Find your auth key in Settings &gt; Auth Key at qaclan.com</p>
      </div>
      <div id="auth-error" style="display:none;color:var(--danger);font-size:13px;margin-top:8px"></div>
      <button class="btn btn-primary" style="width:100%;margin-top:20px" onclick="submitAuthKey()">Log In</button>
    </div>`

  setTimeout(() => document.getElementById('auth-key-input')?.focus(), 50)

  document.getElementById('auth-key-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitAuthKey()
  })
}

async function submitAuthKey() {
  const input = document.getElementById('auth-key-input')
  const errEl = document.getElementById('auth-error')
  const key = input.value.trim()
  if (!key) { errEl.textContent = 'Please enter your auth key'; errEl.style.display = 'block'; return }

  errEl.style.display = 'none'
  const res = await api('POST', '/auth/save', { auth_key: key })
  if (!res.ok) {
    errEl.textContent = res.error || 'Invalid auth key'
    errEl.style.display = 'block'
    return
  }

  state.authenticated = true
  state.user = res.user || null

  const screen = document.getElementById('auth-screen')
  if (screen) screen.remove()
  document.getElementById('app').style.display = ''

  // Continue normal init
  const projRes = await api('GET', '/projects/active')
  if (projRes.id) state.activeProject = { id: projRes.id, name: projRes.name }
  renderSidebar()
  renderTopbar()
  await routes[state.page]()

  toast('Logged in as ' + (res.user?.name || 'user'))
}

// ── Settings Page ──────────────────────────────────────────────

function iconSettings() {
  return '<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3"><circle cx="7.5" cy="7.5" r="2.2"/><path d="M7.5 1.5v1.5M7.5 12v1.5M1.5 7.5H3M12 7.5h1.5M3.4 3.4l1 1M10.6 10.6l1 1M3.4 11.6l1-1M10.6 4.4l1-1"/></svg>'
}

async function renderSettingsPage() {
  const page = document.getElementById('page-content')

  const authRes = await api('GET', '/auth/status')
  const user = authRes.user
  const masked = user ? '••••••••••••' : ''

  page.innerHTML = `
    <div style="max-width:560px">
      <div class="card" style="margin-bottom:16px">
        <div class="card-header">
          <span>Auth Key</span>
        </div>
        <div class="card-body">
          ${user ? `
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
              ${user.avatar_url ? `<img src="${escHtml(user.avatar_url)}" style="width:36px;height:36px;border-radius:50%">` : ''}
              <div>
                <div style="font-weight:500;color:var(--text-primary)">${escHtml(user.name || '')}</div>
                <div class="text-muted" style="font-size:12px">${escHtml(user.email || '')}</div>
              </div>
              <span class="badge badge-success" style="margin-left:auto">Connected</span>
            </div>
          ` : `
            <div style="margin-bottom:16px">
              <span class="badge badge-danger">Not connected</span>
            </div>
          `}
          <div class="form-group">
            <label class="form-label">Auth Key</label>
            <input type="password" id="settings-auth-key" value="${masked}" placeholder="qc_..." style="width:100%">
            <p class="text-muted" style="margin-top:6px;font-size:11px">Find your auth key in Settings &gt; Auth Key at qaclan.com</p>
          </div>
          <div id="settings-auth-error" style="display:none;color:var(--danger);font-size:13px;margin-top:8px"></div>
          <div style="display:flex;gap:8px;margin-top:16px">
            <button class="btn btn-primary btn-sm" onclick="updateAuthKey()">Update Key</button>
            ${user ? `<button class="btn btn-outline-danger btn-sm" onclick="logoutFromSettings()">Disconnect</button>` : ''}
          </div>
        </div>
      </div>
    </div>`

  document.getElementById('settings-auth-key').addEventListener('focus', function() {
    if (this.value === masked) this.value = ''
    this.type = 'text'
  })
  document.getElementById('settings-auth-key').addEventListener('blur', function() {
    if (!this.value.trim() && user) { this.value = masked; this.type = 'password' }
  })
}

async function updateAuthKey() {
  const input = document.getElementById('settings-auth-key')
  const errEl = document.getElementById('settings-auth-error')
  const key = input.value.trim()
  if (!key || key === '••••••••••••') { errEl.textContent = 'Please enter a new auth key'; errEl.style.display = 'block'; return }

  errEl.style.display = 'none'
  const res = await api('POST', '/auth/save', { auth_key: key })
  if (!res.ok) {
    errEl.textContent = res.error || 'Invalid auth key'
    errEl.style.display = 'block'
    return
  }

  state.user = res.user || null
  toast('Auth key updated')
  await renderSettingsPage()
}

async function logoutFromSettings() {
  showModal('Disconnect', `
    <p>Remove your auth key? You will need to enter it again to use QAClan.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Disconnect', cls: 'btn-danger', action: async () => {
      await api('POST', '/auth/remove')
      state.authenticated = false
      state.user = null
      closeModal()
      renderAuthScreen()
    }}
  ])
}

// ── Features Page ───────────────────────────────────────────────

async function renderFeaturesPage() {
  const page = document.getElementById('page-content')
  if (!state.activeProject) { renderNoProject(page); return }

  const res = await api('GET', '/features')
  const features = res.features || []

  page.innerHTML = `
    <div class="page-header">
      <div class="page-header-text">
        <h2>Features</h2>
        <p>Group scripts by application feature</p>
      </div>
      <button class="btn btn-primary" onclick="createFeatureModal()">+ New Feature</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Feature</th>
          <th>Scripts</th>
          <th>Created</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${features.length === 0
            ? `<tr><td colspan="4"><div class="empty-state"><div class="empty-state-icon">\u25C8</div><p>No features yet.<br>Create your first feature to get started.</p></div></td></tr>`
            : features.map(f => `
            <tr>
              <td><strong>${escHtml(f.name)}</strong></td>
              <td><span class="badge badge-neutral">${f.script_count} scripts</span></td>
              <td class="text-muted text-sm">${fmtDate(f.created_at)}</td>
              <td><div class="table-actions">
                <button class="btn btn-xs btn-ghost" onclick="editFeatureModal('${f.id}','${escHtml(f.name)}')">Edit</button>
                <button class="btn btn-xs btn-outline-danger" onclick="deleteFeature('${f.id}','${escHtml(f.name)}')">Delete</button>
              </div></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`
}

async function editFeatureModal(id, name) {
  showModal('Edit Feature', `
    <div class="form-group">
      <label class="form-label">Feature Name</label>
      <input type="text" id="edit-feat-name" value="${name}" autofocus>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Save', cls: 'btn-primary', action: async () => {
      const newName = document.getElementById('edit-feat-name').value.trim()
      if (!newName) return
      const res = await api('PUT', '/features/' + id, { name: newName })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Feature renamed')
      renderFeaturesPage()
    }}
  ])
}

async function createFeatureModal() {
  showModal('New Feature', `
    <div class="form-group">
      <label class="form-label">Feature Name</label>
      <input type="text" id="feat-name" placeholder="e.g. Authentication" autofocus>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Create Feature', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('feat-name').value.trim()
      if (!name) return
      const res = await api('POST', '/features', { name })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Feature "' + name + '" created')
      renderFeaturesPage()
    }}
  ])
}

async function deleteFeature(id, name) {
  showModal('Delete Feature', `
    <p>Delete feature <strong>"${name}"</strong> and all its scripts?</p>
    <p class="text-muted mt-4">This action cannot be undone.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Delete', cls: 'btn-danger', action: async () => {
      const res = await api('DELETE', '/features/' + id)
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Feature deleted')
      renderFeaturesPage()
    }}
  ])
}

// ── Scripts Page ────────────────────────────────────────────────

async function renderScriptsPage() {
  const page = document.getElementById('page-content')
  if (!state.activeProject) { renderNoProject(page); return }

  const [scriptsRes, featuresRes] = await Promise.all([
    api('GET', '/scripts'),
    api('GET', '/features')
  ])
  const scripts = scriptsRes.scripts || []
  const features = featuresRes.features || []

  window._features = features

  const selectedFeature = window._scriptsFilterFeature || ''
  const filtered = selectedFeature
    ? scripts.filter(s => s.feature_id === selectedFeature)
    : scripts

  page.innerHTML = `
    <div class="page-header">
      <div class="page-header-text">
        <h2>Scripts</h2>
        <p>Playwright automation scripts</p>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-ghost" onclick="recordScriptModal()">Record</button>
        <button class="btn btn-primary" onclick="createScriptModal()">+ New Script</button>
      </div>
    </div>
    <div class="filter-bar">
      <select class="filter-select" onchange="window._scriptsFilterFeature=this.value;renderScriptsPage()">
        <option value="">All Features</option>
        ${features.map(f => `<option value="${f.id}" ${f.id === selectedFeature ? 'selected' : ''}>${escHtml(f.name)}</option>`).join('')}
      </select>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Name</th>
          <th>Feature</th>
          <th>Created</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${filtered.length === 0
            ? `<tr><td colspan="4"><div class="empty-state"><div class="empty-state-icon">\u2328</div><p>No scripts yet.</p></div></td></tr>`
            : filtered.map(s => `
            <tr>
              <td><strong>${escHtml(s.name)}</strong></td>
              <td><span class="text-muted text-sm">${escHtml(s.feature_name||'\u2014')}</span></td>
              <td class="text-muted text-sm">${fmtDate(s.created_at)}</td>
              <td><div class="table-actions">
                <button class="btn btn-xs btn-ghost" onclick="viewScriptModal('${s.id}')">View</button>
                <button class="btn btn-xs btn-ghost" onclick="editScriptModal('${s.id}')">Edit</button>
                <button class="btn btn-xs btn-outline-danger" onclick="deleteScript('${s.id}','${escHtml(s.name)}')">Delete</button>
              </div></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`
}

async function recordScriptModal() {
  const features = window._features || []
  if (features.length === 0) { toast('Create a feature first', 'error'); return }

  // Load environments for the dropdown
  const envsRes = await api('GET', '/envs')
  const envs = envsRes.environments || []

  showModal('Record Script', `
    <div class="form-group">
      <label class="form-label">Script Name</label>
      <input type="text" id="rec-name" placeholder="e.g. Login flow" autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Feature</label>
      <select id="rec-feature">
        ${features.map(f => `<option value="${f.id}">${escHtml(f.name)}</option>`).join('')}
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Language</label>
      <select id="rec-language">
        <option value="python" selected>Python</option>
        <option value="javascript">JavaScript</option>
        <option value="typescript">TypeScript</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Environment (optional)</label>
      <select id="rec-env" onchange="_onRecordEnvChange()">
        <option value="">— No environment —</option>
        ${envs.map(e => `<option value="${escHtml(e.name)}">${escHtml(e.name)}</option>`).join('')}
      </select>
    </div>
    <div class="form-group" id="rec-url-key-group" style="display:none">
      <label class="form-label">URL Variable</label>
      <select id="rec-url-key"></select>
      <p class="text-muted" id="rec-url-key-hint" style="margin-top:4px;font-size:11px"></p>
    </div>
    <div class="form-group" id="rec-path-group" style="display:none">
      <label class="form-label">Path (optional)</label>
      <input type="text" id="rec-path" placeholder="e.g. /login">
    </div>
    <div class="form-group" id="rec-url-group">
      <label class="form-label">Start URL (optional)</label>
      <input type="text" id="rec-url" placeholder="e.g. https://myapp.com">
    </div>
    <p class="text-muted">A browser will open for recording. Interact with your app, then close the browser when done.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Start Recording', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('rec-name').value.trim()
      const feature_id = document.getElementById('rec-feature').value
      const language = document.getElementById('rec-language').value
      const env_name = document.getElementById('rec-env').value
      const url_key = document.getElementById('rec-url-key')?.value || ''
      const path_suffix = document.getElementById('rec-path')?.value.trim() || ''
      const url = document.getElementById('rec-url').value.trim()
      if (!name || !feature_id) { toast('Name and feature required', 'error'); return }

      document.querySelector('.modal-body').innerHTML = `
        <div class="loading-state">
          <div class="spinner spinner-lg"></div>
          <p>Recording in progress...<br><span class="text-muted">Close the browser when done.</span></p>
        </div>`
      document.querySelector('.modal-footer').innerHTML = ''

      const payload = { name, feature_id, language }
      if (env_name && url_key) {
        payload.env_name = env_name
        payload.url_key = url_key
        if (path_suffix) payload.path_suffix = path_suffix
      } else if (url) {
        payload.url = url
      }

      const res = await api('POST', '/scripts/record', payload)
      if (res.ok === false) { closeModal(); toast(res.error, 'error'); return }
      closeModal(); toast('Script "' + name + '" recorded')

      // Post-record: load script and trigger field review if any .fill() calls exist
      await reviewRecordedScriptFields(res.id, env_name)
      renderScriptsPage()
    }}
  ])
}

// ── Field detection & review (Phase B) ──────────────────────────

function _parseFillCalls(scriptBody) {
  // Extract every .fill(...) call. Supports two forms:
  //   1. Two-arg legacy:   page.fill("#email", "value")
  //   2. Chained semantic: page.get_by_role("textbox", name="Email").fill("value")
  //                        page.locator("#email").fill("value")
  // For both, we capture:
  //   - locator: the descriptive text used for categorization
  //     (legacy: the first arg; chained: the chain expression like 'get_by_role("textbox", name="Email")')
  //   - value: the filled-in string
  //   - matchStart/matchEnd/fullMatch: only the .fill(...) call itself, for in-place rewrite
  const calls = []

  // Pass 1 — two-arg legacy form: .fill("locator", "value")
  const legacyRe = /\.fill\(\s*(["'])((?:\\.|(?!\1).)*)\1\s*,\s*(["'])((?:\\.|(?!\3).)*)\3\s*\)/g
  let m
  while ((m = legacyRe.exec(scriptBody)) !== null) {
    calls.push({
      locator: m[2],
      value: m[4],
      valueQuote: m[3],
      matchStart: m.index,
      matchEnd: m.index + m[0].length,
      fullMatch: m[0],
    })
  }

  // Pass 2 — single-arg chained form: <chain>.fill("value")
  // The chain may include get_by_role/get_by_label/etc. with their own quoted args.
  // To avoid conflicting with the legacy form, skip matches where the .fill( has a comma inside.
  const singleRe = /\.fill\(\s*(["'])((?:\\.|(?!\1).)*)\1\s*\)/g
  while ((m = singleRe.exec(scriptBody)) !== null) {
    // Walk backward from m.index to find the start of the chain on the same line
    // (chains can span lines but Playwright codegen keeps each .fill on a single line)
    const lineStart = scriptBody.lastIndexOf('\n', m.index) + 1
    const linePrefix = scriptBody.slice(lineStart, m.index)
    // Strip leading whitespace and `await ` if present
    const chain = linePrefix.replace(/^\s*(await\s+)?/, '')

    calls.push({
      locator: chain,
      value: m[2],
      valueQuote: m[1],
      matchStart: m.index,
      matchEnd: m.index + m[0].length,
      fullMatch: m[0],
    })
  }

  // Sort by position so the review modal shows fields in script order
  calls.sort((a, b) => a.matchStart - b.matchStart)
  return calls
}

function _categorizeField(locator, patterns) {
  // patterns: { category: { patterns: [...], canonical_key: "..." }, ... }
  // Returns the category name whose pattern list has the longest substring match,
  // or null if no category matches.
  const lower = locator.toLowerCase()
  let bestCategory = null
  let bestLen = 0
  for (const [category, cfg] of Object.entries(patterns || {})) {
    const words = Array.isArray(cfg) ? cfg : (cfg.patterns || [])
    for (const word of words) {
      if (word && lower.includes(word.toLowerCase()) && word.length > bestLen) {
        bestCategory = category
        bestLen = word.length
      }
    }
  }
  return bestCategory
}

function _suggestEnvKeysForCategory(category, envVars, secretCategories) {
  // Return env vars sorted by likelihood of matching the category.
  // Score: substring match against category and its synonyms = high, others = low.
  // For secret categories, only suggest is_secret=true vars.
  if (!category || !envVars) return []
  const isSecretCat = secretCategories && secretCategories.includes(category)
  const candidates = isSecretCat ? envVars.filter(v => v.is_secret) : envVars

  const cat = category.toLowerCase()
  return candidates
    .map(v => {
      const k = v.key.toLowerCase()
      let score = 0
      if (k.includes(cat)) score += 10
      if (cat === 'username' && (k.includes('user') || k.includes('email') || k.includes('login'))) score += 5
      if (cat === 'password' && (k.includes('pass') || k.includes('pwd'))) score += 5
      if (cat === 'tenant' && (k.includes('tenant') || k.includes('org') || k.includes('workspace'))) score += 5
      if (cat === 'token' && (k.includes('token') || k.includes('key') || k.includes('secret'))) score += 5
      return { ...v, _score: score }
    })
    .sort((a, b) => b._score - a._score)
}

async function reviewRecordedScriptFields(scriptId, envName) {
  // Load the recorded script + sensitive patterns
  const sRes = await api('GET', '/scripts/' + scriptId)
  if (sRes.ok === false) return
  const script = sRes.script || sRes
  const content = script.content || ''

  const fills = _parseFillCalls(content)
  if (fills.length === 0) return  // nothing to review

  const patternsRes = await api('GET', '/scripts/sensitive-patterns')
  const patterns = patternsRes.patterns || {}
  const secretCats = patternsRes.secret_categories || []

  // Categorize each fill
  const categorized = fills.map((f, i) => ({
    ...f,
    index: i,
    category: _categorizeField(f.locator, patterns),
  }))
  const sensitiveFills = categorized.filter(f => f.category)
  if (sensitiveFills.length === 0 && fills.length === 0) return

  // Load env vars for suggestions (if user picked an env at record time)
  let envVars = []
  if (envName) {
    const eRes = await api('GET', '/envs/' + encodeURIComponent(envName))
    envVars = eRes.variables || []
  }

  await _showFieldReviewModal(scriptId, content, categorized, envVars, secretCats, envName, patterns)
}

function _lineNumberAt(content, offset) {
  // 1-indexed line number for a given character offset
  let line = 1
  for (let i = 0; i < offset && i < content.length; i++) {
    if (content[i] === '\n') line++
  }
  return line
}

function _lineTextAt(content, offset) {
  const start = content.lastIndexOf('\n', offset - 1) + 1
  let end = content.indexOf('\n', offset)
  if (end === -1) end = content.length
  return content.slice(start, end)
}

function _renderDiffLine(lineText, value, valueQuote, mode, replacementKey) {
  // Render a line with the target value (wrapped in its quotes) highlighted.
  // mode: 'before' = red strikethrough on the value;
  //       'after'  = the value span replaced with {{KEY}} on a green background.
  const target = valueQuote + value + valueQuote
  const idx = lineText.lastIndexOf(target)
  if (idx === -1) return escHtml(lineText)
  const head = escHtml(lineText.slice(0, idx))
  const tail = escHtml(lineText.slice(idx + target.length))
  if (mode === 'before') {
    return head + `<span class="diff-highlight-before">${escHtml(target)}</span>` + tail
  }
  // 'after' — show the replacement with the quote marks preserved around {{KEY}}
  const newInner = valueQuote + '{{' + (replacementKey || '') + '}}' + valueQuote
  return head + `<span class="diff-highlight-after">${escHtml(newInner)}</span>` + tail
}

async function _showFieldReviewModalCore({ fills, originalContent, envVars, secretCats, envName, patterns, onApply, onSkip, useOverlay = false }) {
  // When called from inside another modal (e.g. editor Scan & Bind), render as an
  // overlay so the underlying modal and its state (textarea value, etc.) stay alive.
  const modalShowFn = useOverlay ? showOverlayModal : showModal
  const modalCloseFn = useOverlay ? closeOverlayModal : closeModal

  const sensitive = fills.filter(f => f.category)
  const others = fills.filter(f => !f.category)

  // Precompute line info per fill so we don't re-walk the content every render
  fills.forEach(f => {
    f.lineNumber = _lineNumberAt(originalContent, f.matchStart)
    f.lineText = _lineTextAt(originalContent, f.matchStart)
  })

  // Load all envs for the env selector
  const envsRes = await api('GET', '/envs')
  const allEnvs = envsRes.environments || []

  // Mutable state: currently loaded env vars (changes when user picks a different env)
  let currentEnvName = envName || ''
  let currentEnvVars = envVars || []

  // Track user selections so they persist across env switches.
  // Map of fillIndex → selectedKey. Updated on every dropdown change.
  const userSelections = new Map()

  // Collect canonical keys for quick lookup
  const canonicalKeys = new Map()  // category → canonical_key
  if (patterns) {
    for (const [cat, cfg] of Object.entries(patterns)) {
      if (cfg.canonical_key) canonicalKeys.set(cat, cfg.canonical_key)
    }
  }

  const categoryAccent = (cat) => {
    if (!cat) return { border: 'var(--border-default)', bg: 'rgba(148,163,184,0.12)', fg: '#cbd5e1' }
    if (secretCats.includes(cat)) return { border: '#f87171', bg: 'rgba(248,113,113,0.14)', fg: '#fca5a5' }
    if (cat === 'username' || cat === 'tenant') return { border: '#60a5fa', bg: 'rgba(96,165,250,0.14)', fg: '#93c5fd' }
    if (cat === 'host') return { border: '#a78bfa', bg: 'rgba(167,139,250,0.14)', fg: '#c4b5fd' }
    return { border: 'var(--border-default)', bg: 'rgba(148,163,184,0.12)', fg: '#cbd5e1' }
  }

  function _buildDropdownOpts(f, envVarsList) {
    const savedKey = userSelections.get(f.index) || ''

    // No env selected yet — show disabled placeholder
    if (!currentEnvName) {
      return '<option value="" selected>— Select environment first —</option>'
    }

    const suggestions = f.category ? _suggestEnvKeysForCategory(f.category, envVarsList, secretCats) : envVarsList
    const envKeySet = new Set(envVarsList.map(v => v.key))

    const optParts = ['<option value=""' + (savedKey === '' ? ' selected' : '') + '>— Skip —</option>']

    // For sensitive fields: always include the canonical key as an option
    if (f.category && canonicalKeys.has(f.category)) {
      const canonical = canonicalKeys.get(f.category)
      const inEnv = envKeySet.has(canonical)
      const label = inEnv ? canonical : canonical + ' (suggested — will be added to env)'
      const isSelected = savedKey === canonical
      // Don't duplicate if the env already has this key (it'll appear in the env list below)
      if (!inEnv) {
        optParts.push(`<option value="${escHtml(canonical)}"${isSelected ? ' selected' : ''}>${escHtml(label)}</option>`)
      }
    }

    // Env keys (sorted by relevance for sensitive, all for non-sensitive)
    optParts.push(...suggestions.map(v => {
      const isSelected = savedKey === v.key
      return `<option value="${escHtml(v.key)}"${isSelected ? ' selected' : ''}>${escHtml(v.key)}</option>`
    }))

    return optParts.join('')
  }

  function renderRow(f) {
    const isSecret = f.category && secretCats.includes(f.category)
    const valuePreview = isSecret ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' : f.value
    const opts = _buildDropdownOpts(f, currentEnvVars)
    const accent = categoryAccent(f.category)
    const categoryLabel = `<span style="display:inline-block;font-size:13px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;padding:5px 12px;border-radius:4px;background:${accent.bg};color:${accent.fg};border:1px solid ${accent.border}">${escHtml(f.category || 'field')}</span>`
    const beforeLineHtml = _renderDiffLine(f.lineText, f.value, f.valueQuote, 'before')
    return `
      <div class="field-review-row" data-fill-index="${f.index}" style="padding:14px 16px;border-bottom:1px solid var(--border-subtle);border-left:3px solid ${accent.border};margin-bottom:2px">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
          ${categoryLabel}
          <span style="font-family:monospace;font-size:12px;font-weight:600;color:var(--text-secondary);background:var(--bg-base);padding:3px 8px;border-radius:3px">L${f.lineNumber}</span>
          <span style="color:var(--text-secondary);font-size:12px">Recorded: <code>${escHtml(valuePreview)}</code></span>
          <select class="field-review-select" style="margin-left:auto;min-width:220px" onchange="_onFieldReviewSelect(${f.index}, this.value)">${opts}</select>
        </div>
        <div style="font-family:monospace;font-size:12px;line-height:1.6;background:var(--bg-base);padding:10px 12px;border-radius:4px;overflow-x:auto">
          <div style="display:flex;gap:10px">
            <span style="color:var(--text-secondary);flex-shrink:0;width:52px">before:</span>
            <span style="color:var(--text-primary);white-space:pre">${beforeLineHtml}</span>
          </div>
          <div style="display:flex;gap:10px;margin-top:4px">
            <span style="color:var(--text-secondary);flex-shrink:0;width:52px">after:</span>
            <span id="preview-after-${f.index}" style="color:var(--text-primary);white-space:pre">${beforeLineHtml}</span>
          </div>
        </div>
      </div>`
  }

  // Track whether user has expanded the "other fields" section so we can
  // preserve that state across env-change re-renders.
  let othersExpanded = false

  function renderFieldRows() {
    const sensitiveBlock = sensitive.length === 0
      ? '<p class="text-muted">No sensitive fields detected.</p>'
      : sensitive.map(renderRow).join('')
    const othersBlock = others.length === 0
      ? ''
      : `<details${othersExpanded ? ' open' : ''} style="margin-top:14px" ontoggle="window._qcOthersToggled && window._qcOthersToggled(this)">
           <summary style="cursor:pointer;color:var(--text-primary);font-size:13px;font-weight:600;padding:8px 0">Show all ${others.length} other fill field${others.length === 1 ? '' : 's'}</summary>
           <div style="margin-top:8px">${others.map(renderRow).join('')}</div>
         </details>`
    return `<div>${sensitiveBlock}</div>${othersBlock}`
  }

  window._qcOthersToggled = function(el) { othersExpanded = el.open }

  // Store fills + originalContent globally so the onchange preview handler can access them
  window._fieldReviewState = { fills, originalContent }

  // Cleanup function: nulls out all window globals this modal sets.
  // Called on close (both Skip and Apply paths, and close-X/backdrop).
  function _cleanupReviewModalGlobals() {
    window._fieldReviewState = null
    window._onFieldReviewSelect = null
    window._onReviewEnvChange = null
    window._qcOthersToggled = null
  }

  // Save user selection and update preview on dropdown change
  window._onFieldReviewSelect = function(fillIndex, key) {
    if (key) {
      userSelections.set(fillIndex, key)
    } else {
      userSelections.delete(fillIndex)
    }
    _updateFieldReviewPreview(fillIndex)
  }

  // Expose the env-change handler globally so the select's onchange can call it
  window._onReviewEnvChange = async function() {
    const modalRoot = useOverlay
      ? document.getElementById('modal-overlay-root')
      : document.getElementById('modal-root')
    if (!modalRoot) return
    const sel = modalRoot.querySelector('#review-env-select')
    if (!sel) return
    currentEnvName = sel.value
    if (currentEnvName) {
      const eRes = await api('GET', '/envs/' + encodeURIComponent(currentEnvName))
      currentEnvVars = eRes.variables || []
    } else {
      currentEnvVars = []
    }
    // Re-render field rows with new env's keys
    const container = modalRoot.querySelector('#review-fields-container')
    if (container) container.innerHTML = renderFieldRows()
    // Re-attach preview state
    window._fieldReviewState = { fills, originalContent }
    // Restore "after" previews for any fields that have a saved selection
    for (const [fillIndex, key] of userSelections.entries()) {
      if (key) _updateFieldReviewPreview(fillIndex)
    }
  }

  const envSelectorHTML = `
    <div class="form-group" style="margin-bottom:14px">
      <label class="form-label" style="font-weight:600">Environment</label>
      <select id="review-env-select" style="width:100%;max-width:300px" onchange="_onReviewEnvChange()">
        <option value="">— Select environment —</option>
        ${allEnvs.map(e => `<option value="${escHtml(e.name)}" ${e.name === currentEnvName ? 'selected' : ''}>${escHtml(e.name)} (${e.var_count} vars)</option>`).join('')}
      </select>
      ${!currentEnvName ? '<p class="form-hint" style="margin-top:4px">Select an environment to see available keys and enable Apply.</p>' : ''}
    </div>`

  modalShowFn('Review Fields', `
    ${envSelectorHTML}
    <p class="form-hint" style="margin-bottom:14px">Bind detected fields to environment variables. Pick a key to preview the result. Skipped fields stay hardcoded.</p>
    <div id="review-fields-container">${renderFieldRows()}</div>`, [
    { label: 'Skip & save as-is', cls: 'btn-ghost', action: () => { modalCloseFn(); onSkip && onSkip() } },
    { label: 'Apply Bindings', cls: 'btn-primary', action: async () => {
      if (!currentEnvName) {
        toast('Select an environment first', 'error')
        return
      }

      // Scope queries to the correct modal root
      const modalRoot = useOverlay
        ? document.getElementById('modal-overlay-root')
        : document.getElementById('modal-root')
      const rows = (modalRoot || document).querySelectorAll('.field-review-row')
      const bindings = []
      rows.forEach(r => {
        const idx = parseInt(r.getAttribute('data-fill-index'), 10)
        const key = r.querySelector('.field-review-select').value
        if (key) bindings.push({ index: idx, key })
      })

      if (bindings.length === 0) {
        modalCloseFn(); onSkip && onSkip(); return
      }

      const newContent = _rewriteScriptWithBindings(originalContent, fills, bindings)

      // Auto-add missing keys to the selected env with recorded values
      const envKeySet = new Set(currentEnvVars.map(v => v.key))
      const missingVars = bindings
        .filter(b => !envKeySet.has(b.key))
        .map(b => {
          const fill = fills[b.index]
          const isSecret = fill && fill.category && secretCats.includes(fill.category)
          return { key: b.key, value: fill ? fill.value : '', is_secret: isSecret ? 1 : 0 }
        })

      if (missingVars.length > 0) {
        const appendRes = await api('POST', '/envs/' + encodeURIComponent(currentEnvName) + '/vars/append', { vars: missingVars })
        if (appendRes.ok !== false && appendRes.added > 0) {
          const keyNames = missingVars.map(v => v.key).join(', ')
          toast('Added ' + keyNames + ' to "' + currentEnvName + '" with recorded values')
        }
      }

      modalCloseFn()
      if (onApply) await onApply(newContent, bindings.length)
    }}
  ], '', 'xl')

  // Register cleanup hook AFTER modalShowFn has rendered. This avoids the bug where
  // showOverlayModal's defensive closeOverlayModal() call would trigger our cleanup
  // before the modal even appeared.
  if (useOverlay) {
    const _origCloseOverlay = window.closeOverlayModal
    window.closeOverlayModal = function() {
      _cleanupReviewModalGlobals()
      window.closeOverlayModal = _origCloseOverlay
      _origCloseOverlay()
    }
  } else {
    const prevHook = window._qcModalCleanupHook
    window._qcModalCleanupHook = () => {
      _cleanupReviewModalGlobals()
      if (typeof prevHook === 'function') prevHook()
    }
  }
}

function _updateFieldReviewPreview(fillIndex) {
  const state = window._fieldReviewState
  if (!state) return
  const fill = state.fills.find(f => f.index === fillIndex)
  if (!fill) return
  const row = document.querySelector(`.field-review-row[data-fill-index="${fillIndex}"]`)
  if (!row) return
  const key = row.querySelector('.field-review-select').value
  const preview = document.getElementById('preview-after-' + fillIndex)
  if (!preview) return

  if (!key) {
    // No binding selected — show the original line (same as "before")
    preview.innerHTML = _renderDiffLine(fill.lineText, fill.value, fill.valueQuote, 'before')
    return
  }
  // Render with the "after" diff highlight (green replacement on the value span)
  preview.innerHTML = _renderDiffLine(fill.lineText, fill.value, fill.valueQuote, 'after', key)
}

// Post-record wrapper that persists via PUT
async function _showFieldReviewModal(scriptId, originalContent, fills, envVars, secretCats, envName, patterns) {
  return new Promise(async (resolve) => {
    await _showFieldReviewModalCore({
      fills, originalContent, envVars, secretCats, envName, patterns,
      onApply: async (newContent, count) => {
        const updateRes = await api('PUT', '/scripts/' + scriptId, { content: newContent })
        if (updateRes.ok === false) toast(updateRes.error, 'error')
        else toast(count + ' field' + (count === 1 ? '' : 's') + ' bound')
        resolve()
      },
      onSkip: () => resolve(),
    })
  })
}

function _rewriteScriptWithBindings(content, fills, bindings) {
  // Replace each bound .fill() value with "{{KEY}}". Apply replacements
  // back-to-front so earlier indices stay valid.
  const sortedBindings = [...bindings].sort((a, b) => b.index - a.index)
  let result = content
  for (const b of sortedBindings) {
    const f = fills[b.index]
    if (!f) continue
    const placeholder = '{{' + b.key + '}}'
    // Replace only the LAST occurrence of the quoted value inside fullMatch.
    // For chained .fill("value") this is the only quoted string.
    // For legacy .fill("loc", "value") the value is always the second/last quoted string,
    // so anchoring on the last occurrence avoids ever touching the locator.
    const target = f.valueQuote + f.value + f.valueQuote
    const replacement = f.valueQuote + placeholder + f.valueQuote
    const lastIdx = f.fullMatch.lastIndexOf(target)
    const newCall = lastIdx >= 0
      ? f.fullMatch.slice(0, lastIdx) + replacement + f.fullMatch.slice(lastIdx + target.length)
      : f.fullMatch
    result = result.slice(0, f.matchStart) + newCall + result.slice(f.matchEnd)
  }
  return result
}

function _escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function _onRecordEnvChange() {
  const envName = document.getElementById('rec-env').value
  const keyGroup = document.getElementById('rec-url-key-group')
  const pathGroup = document.getElementById('rec-path-group')
  const urlGroup = document.getElementById('rec-url-group')
  const keySelect = document.getElementById('rec-url-key')
  const hint = document.getElementById('rec-url-key-hint')

  if (!envName) {
    keyGroup.style.display = 'none'
    pathGroup.style.display = 'none'
    urlGroup.style.display = ''
    return
  }

  // Fetch the env vars for the selected env
  const res = await api('GET', '/envs/' + encodeURIComponent(envName))
  const allVars = res.variables || []
  // Filter to URL-shaped values only
  const urlVars = allVars.filter(v => /^https?:\/\//.test(v.value))

  if (urlVars.length === 0) {
    keyGroup.style.display = ''
    pathGroup.style.display = 'none'
    urlGroup.style.display = ''
    keySelect.innerHTML = '<option value="">— No URL variables in this env —</option>'
    keySelect.disabled = true
    hint.textContent = 'Add a variable with an http:// or https:// value to "' + envName + '" to use it here.'
    return
  }

  keySelect.disabled = false
  keySelect.innerHTML = urlVars.map(v =>
    `<option value="${escHtml(v.key)}" data-url="${escHtml(v.value)}">${escHtml(v.key)} — ${escHtml(v.value)}</option>`
  ).join('')
  keyGroup.style.display = ''
  pathGroup.style.display = ''
  urlGroup.style.display = 'none'
  hint.textContent = ''
}

async function createScriptModal() {
  const features = window._features || []
  const envsRes = await api('GET', '/envs')
  const envs = envsRes.environments || []
  showModal('New Script', `
    <div class="form-group">
      <label class="form-label">Script Name</label>
      <input type="text" id="script-name" placeholder="e.g. Login test">
    </div>
    <div class="form-group">
      <label class="form-label">Feature</label>
      <select id="script-feature">
        ${features.map(f => `<option value="${f.id}">${escHtml(f.name)}</option>`).join('')}
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Language</label>
      <select id="script-language">
        <option value="python" selected>Python</option>
        <option value="javascript">JavaScript</option>
        <option value="typescript">TypeScript</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Insert Variable</label>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <select id="insert-var-env" style="flex:1;min-width:150px" onchange="_loadEnvKeysForInsert()">
          <option value="">— Select env —</option>
          ${envs.map(e => `<option value="${escHtml(e.name)}">${escHtml(e.name)}</option>`).join('')}
        </select>
        <select id="insert-var-key" style="flex:1;min-width:150px" disabled>
          <option value="">— Pick env first —</option>
        </select>
        <button type="button" class="btn btn-sm btn-ghost" onclick="_insertVarAtCursor()">Insert at cursor</button>
        <button type="button" class="btn btn-sm btn-ghost" onclick="scanAndBindFromEditor()">Scan &amp; Bind</button>
      </div>
      <p class="form-hint"><strong style="color:var(--text-primary)">Insert</strong> inserts <code>{{KEY}}</code> at the cursor. <strong style="color:var(--text-primary)">Scan &amp; Bind</strong> reviews every <code>.fill()</code> in the current content.</p>
    </div>
    <div class="form-group">
      <label class="form-label">Script Content</label>
      <div id="create-script-editor-host"></div>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Create Script', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('script-name').value.trim()
      const feature_id = document.getElementById('script-feature').value
      const language = document.getElementById('script-language').value
      const content = window._qcCurrentEditor ? window._qcCurrentEditor.getValue() : ''
      if (!name || !feature_id) { toast('Name and feature required', 'error'); return }
      const res = await api('POST', '/scripts', { name, feature_id, language, content })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Script "' + name + '" created')
      renderScriptsPage()
    }}
  ], '', 'lg')

  const host = document.getElementById('create-script-editor-host')
  if (host) {
    const editor = _createScriptEditor(host, '')
    window._qcCurrentEditor = editor
    window._qcModalCleanupHook = () => {
      editor.destroy()
      if (window._qcCurrentEditor === editor) window._qcCurrentEditor = null
    }

    const langSelect = document.getElementById('script-language')
    let lastTemplate = ''

    const loadTemplate = async (lang) => {
      const res = await api('GET', '/scripts/starter-template?language=' + encodeURIComponent(lang))
      if (res && res.ok !== false && typeof res.content === 'string') {
        return res.content
      }
      return ''
    }

    loadTemplate(langSelect.value).then(tpl => {
      lastTemplate = tpl
      if (editor.getValue() === '') editor.setValue(tpl)
    })

    langSelect.addEventListener('change', async () => {
      const current = editor.getValue()
      const newTpl = await loadTemplate(langSelect.value)
      if (current === '' || current === lastTemplate) {
        editor.setValue(newTpl)
      } else {
        toast('Language changed — existing content kept. Clear the editor to use the new starter template.')
      }
      lastTemplate = newTpl
    })
  }
}

function _scriptProvenanceHTML(s) {
  const parts = []
  if (s.start_url_key && s.start_url_value) {
    parts.push(`<div style="color:var(--text-secondary)"><strong style="color:var(--text-primary);font-weight:600">Recorded against:</strong> <code>${escHtml(s.start_url_key)}</code> = <code>${escHtml(s.start_url_value)}</code></div>`)
  } else if (s.start_url_value) {
    parts.push(`<div style="color:var(--text-secondary)"><strong style="color:var(--text-primary);font-weight:600">Recorded URL:</strong> <code>${escHtml(s.start_url_value)}</code></div>`)
  }
  const keys = Array.isArray(s.var_keys) ? s.var_keys : []
  if (keys.length > 0) {
    parts.push(`<div style="color:var(--text-secondary);display:flex;align-items:center;gap:6px;flex-wrap:wrap"><strong style="color:var(--text-primary);font-weight:600">Depends on:</strong> ${keys.map(k => `<span class="badge badge-neutral">${escHtml(k)}</span>`).join('')}</div>`)
  }
  if (parts.length === 0) return ''
  return `<div class="form-group" style="font-size:13px;display:flex;flex-direction:column;gap:6px;padding:10px 12px;background:var(--bg-base);border-radius:6px">${parts.join('')}</div>`
}

async function viewScriptModal(id) {
  const res = await api('GET', '/scripts/' + id)
  if (res.ok === false) { toast(res.error, 'error'); return }
  const s = res.script || res
  showModal('View Script', `
    <div class="form-group">
      <label class="form-label">Name</label>
      <p>${escHtml(s.name)}</p>
    </div>
    ${_scriptProvenanceHTML(s)}
    <div class="form-group">
      <label class="form-label">Content</label>
      <div id="view-script-editor-host"></div>
    </div>`, [
    { label: 'Close', cls: 'btn-ghost', action: closeModal }
  ], 'Script ID: ' + s.id, 'lg')

  // Render the editor after the modal is in the DOM
  const host = document.getElementById('view-script-editor-host')
  if (host) {
    const editor = _createScriptEditor(host, s.content || '', { readOnly: true })
    window._qcCurrentEditor = editor
    window._qcModalCleanupHook = () => {
      editor.destroy()
      if (window._qcCurrentEditor === editor) window._qcCurrentEditor = null
    }
  }
}

async function editScriptModal(id) {
  const sRes = await api('GET', '/scripts/' + id)
  if (sRes.ok === false) { toast(sRes.error, 'error'); return }
  const s = sRes.script || sRes
  const envsRes = await api('GET', '/envs')
  const envs = envsRes.environments || []
  const lang = s.language || 'python'
  const langLabel = { python: 'Python', javascript: 'JavaScript', typescript: 'TypeScript' }[lang] || lang
  showModal('Edit Script', `
    <div class="form-group">
      <label class="form-label">Script Name</label>
      <input type="text" id="edit-script-name" value="${escHtml(s.name)}">
    </div>
    <div class="form-group">
      <label class="form-label">Language</label>
      <div style="display:flex;align-items:center;gap:8px">
        <span class="badge badge-neutral">${escHtml(langLabel)}</span>
        <span class="form-hint" style="margin:0">Language is set at creation time.</span>
      </div>
    </div>
    ${_scriptProvenanceHTML(s)}
    <div class="form-group">
      <label class="form-label">Insert Variable</label>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <select id="insert-var-env" style="flex:1;min-width:150px" onchange="_loadEnvKeysForInsert()">
          <option value="">— Select env —</option>
          ${envs.map(e => `<option value="${escHtml(e.name)}">${escHtml(e.name)}</option>`).join('')}
        </select>
        <select id="insert-var-key" style="flex:1;min-width:150px" disabled>
          <option value="">— Pick env first —</option>
        </select>
        <button type="button" class="btn btn-sm btn-ghost" onclick="_insertVarAtCursor()">Insert at cursor</button>
        <button type="button" class="btn btn-sm btn-ghost" onclick="scanAndBindFromEditor()">Scan &amp; Bind</button>
      </div>
      <p class="form-hint"><strong style="color:var(--text-primary)">Insert</strong> inserts <code>{{KEY}}</code> at the cursor. <strong style="color:var(--text-primary)">Scan &amp; Bind</strong> reviews every <code>.fill()</code> in the current content.</p>
    </div>
    <div class="form-group">
      <label class="form-label">Content</label>
      <div id="edit-script-editor-host"></div>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Save', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('edit-script-name').value.trim()
      const content = window._qcCurrentEditor ? window._qcCurrentEditor.getValue() : ''
      if (!name) return
      const res = await api('PUT', '/scripts/' + id, { name, content })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Script updated')
      renderScriptsPage()
    }}
  ], 'Script ID: ' + s.id, 'lg')

  const host = document.getElementById('edit-script-editor-host')
  if (host) {
    const editor = _createScriptEditor(host, s.content || '')
    window._qcCurrentEditor = editor
    window._qcModalCleanupHook = () => {
      editor.destroy()
      if (window._qcCurrentEditor === editor) window._qcCurrentEditor = null
    }
  }
}

async function _loadEnvKeysForInsert() {
  const envName = document.getElementById('insert-var-env').value
  const keySelect = document.getElementById('insert-var-key')
  if (!envName) {
    keySelect.innerHTML = '<option value="">— Pick env first —</option>'
    keySelect.disabled = true
    return
  }
  const res = await api('GET', '/envs/' + encodeURIComponent(envName))
  const vars = res.variables || []
  if (vars.length === 0) {
    keySelect.innerHTML = '<option value="">— No vars in this env —</option>'
    keySelect.disabled = true
    return
  }
  keySelect.disabled = false
  keySelect.innerHTML = vars.map(v =>
    `<option value="${escHtml(v.key)}">${escHtml(v.key)}</option>`
  ).join('')
}

function _insertVarAtCursor() {
  const key = document.getElementById('insert-var-key').value
  if (!key) { toast('Pick a variable first', 'error'); return }
  const editor = window._qcCurrentEditor
  if (!editor) return
  editor.insertAtCursor('{{' + key + '}}')
}

function _scrollTextareaToCaret(ta, caretPos) {
  // Estimate line height from computed style, count newlines up to caret,
  // and scroll so the caret line is roughly centered in the viewport.
  const cs = window.getComputedStyle(ta)
  const lineHeight = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4 || 18
  const linesBeforeCaret = (ta.value.slice(0, caretPos).match(/\n/g) || []).length
  const targetScroll = Math.max(0, (linesBeforeCaret * lineHeight) - (ta.clientHeight / 2))
  ta.scrollTop = targetScroll
}

function _flashTextareaBackground(ta) {
  // Brief yellow flash so the user sees "something happened here" on big scripts
  const prevBg = ta.style.backgroundColor
  const prevTransition = ta.style.transition
  ta.style.transition = 'background-color 0.1s ease'
  ta.style.backgroundColor = 'rgba(250, 204, 21, 0.22)'
  setTimeout(() => {
    ta.style.transition = 'background-color 0.6s ease'
    ta.style.backgroundColor = prevBg || ''
    setTimeout(() => { ta.style.transition = prevTransition || '' }, 700)
  }, 150)
}

async function scanAndBindFromEditor() {
  const editor = window._qcCurrentEditor
  if (!editor) return
  const content = editor.getValue()
  const fills = _parseFillCalls(content)
  if (fills.length === 0) { toast('No .fill() calls found in script', 'error'); return }

  const patternsRes = await api('GET', '/scripts/sensitive-patterns')
  const patterns = patternsRes.patterns || {}
  const secretCats = patternsRes.secret_categories || []

  // Use the env currently selected in the Insert Variable picker as the source for suggestions
  const envName = document.getElementById('insert-var-env')?.value || ''
  let envVars = []
  if (envName) {
    const eRes = await api('GET', '/envs/' + encodeURIComponent(envName))
    envVars = eRes.variables || []
  } else {
    // Fallback: try to offer the union of all envs' keys so user isn't stuck
    const envsRes = await api('GET', '/envs')
    const envs = envsRes.environments || []
    const seen = new Set()
    for (const e of envs) {
      const r = await api('GET', '/envs/' + encodeURIComponent(e.name))
      for (const v of (r.variables || [])) {
        if (!seen.has(v.key)) { seen.add(v.key); envVars.push(v) }
      }
    }
  }

  const categorized = fills.map((f, i) => ({
    ...f,
    index: i,
    category: _categorizeField(f.locator, patterns),
  }))

  // Apply bindings in-memory, then write back to the editor via the wrapper API
  await _showFieldReviewModalForEditor(content, categorized, envVars, secretCats, envName, patterns)
}

async function _showFieldReviewModalForEditor(originalContent, fills, envVars, secretCats, envName, patterns) {
  await _showFieldReviewModalCore({
    fills,
    originalContent,
    envVars,
    secretCats,
    envName,
    patterns,
    useOverlay: true,  // render on top of the existing edit/create script modal
    onApply: (newContent) => {
      const editor = window._qcCurrentEditor
      if (editor) {
        editor.setValue(newContent)
        editor.focus()
      }
    },
    onSkip: () => {},
  })
}

async function deleteScript(id, name) {
  showModal('Delete Script', `
    <p>Delete script <strong>"${name}"</strong>?</p>
    <p class="text-muted mt-4">This will also remove it from any suites.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Delete', cls: 'btn-danger', action: async () => {
      const res = await api('DELETE', '/scripts/' + id)
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Script deleted')
      renderScriptsPage()
    }}
  ])
}

// ── Suites Page ─────────────────────────────────────────────────

async function renderSuitesPage() {
  const page = document.getElementById('page-content')
  if (!state.activeProject) { renderNoProject(page); return }

  const res = await api('GET', '/suites')
  const suites = res.suites || []

  page.innerHTML = `
    <div class="page-header">
      <div class="page-header-text">
        <h2>Suites</h2>
        <p>Manage regression suites</p>
      </div>
      <button class="btn btn-primary" onclick="createSuiteModal()">+ New Suite</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Suite</th>
          <th>ID</th>
          <th>Scripts</th>
          <th>Last Run</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${suites.length === 0
            ? `<tr><td colspan="5"><div class="empty-state"><div class="empty-state-icon">\u25A6</div><p>No suites yet.</p></div></td></tr>`
            : suites.map(s => `
            <tr>
              <td><strong>${escHtml(s.name)}</strong></td>
              <td>
                ${s.cloud_id ? `
                  <button class="id-chip" onclick="copyToClipboard('${s.cloud_id}', this)" title="Cloud ID: ${s.cloud_id} — click to copy">
                    <code>${s.cloud_id.slice(0, 8)}\u2026${s.cloud_id.slice(-4)}</code>
                    <span class="id-chip-icon">\u2398</span>
                  </button>
                ` : '<span class="text-muted text-sm">Not synced</span>'}
              </td>
              <td><span class="badge badge-neutral">${s.script_count} scripts</span></td>
              <td>${s.last_run_status
                ? `<span class="badge ${s.last_run_status==='PASSED'?'badge-success':'badge-danger'}"><span class="badge-dot"></span>${s.last_run_status}</span>`
                : '<span class="text-muted text-sm">Never</span>'}</td>
              <td><div class="table-actions">
                <button class="btn btn-xs btn-ghost" onclick="editSuiteModal('${s.id}')">Edit</button>
                <button class="btn btn-xs btn-primary" onclick="runSuiteModal('${s.id}','${escHtml(s.name)}')">Run</button>
                <button class="btn btn-xs btn-outline-danger" onclick="deleteSuite('${s.id}','${escHtml(s.name)}')">Delete</button>
              </div></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`
}

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text)
    if (btn) {
      btn.classList.add('copied')
      setTimeout(() => btn.classList.remove('copied'), 1200)
    }
    toast('Copied: ' + text, 'success')
  } catch (e) {
    toast('Copy failed', 'error')
  }
}

function createSuiteModal() {
  showModal('New Suite', `
    <div class="form-group">
      <label class="form-label">Suite Name</label>
      <input type="text" id="suite-name" placeholder="e.g. Smoke Tests" autofocus>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Create Suite', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('suite-name').value.trim()
      if (!name) return
      const res = await api('POST', '/suites', { name })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Suite "' + name + '" created')
      renderSuitesPage()
    }}
  ])
}

async function editSuiteModal(id) {
  const [suiteRes, scriptsRes] = await Promise.all([
    api('GET', '/suites/' + id),
    api('GET', '/scripts')
  ])
  if (suiteRes.ok === false) { toast(suiteRes.error, 'error'); return }
  const suite = suiteRes.suite || suiteRes
  const allScripts = scriptsRes.scripts || []
  const suiteScripts = suite.scripts || []

  function renderBody() {
    const scriptOpts = allScripts
      .filter(s => !suiteScripts.find(ss => ss.script_id === s.id))
      .map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('')

    return `
      <div class="form-group">
        <label class="form-label">Suite Name</label>
        <div class="input-row">
          <input type="text" id="edit-suite-name" value="${escHtml(suite.name)}">
          <button class="btn btn-sm btn-ghost" onclick="renameSuite('${id}')">Rename</button>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Scripts</label>
      </div>
      <div class="suite-script-list" id="suite-script-list">
        ${suiteScripts.length === 0
          ? '<p class="text-muted">No scripts in this suite yet.</p>'
          : suiteScripts.map((s, i) => `
          <div class="suite-script-row" draggable="true" data-script-id="${s.script_id}">
            <span class="suite-script-drag">⠿</span>
            <span class="suite-script-order">${i + 1}</span>
            <span class="suite-script-name">${escHtml(s.name)}</span>
            <button class="btn btn-xs btn-outline-danger" onclick="removeSuiteScript('${id}','${s.script_id}')">Remove</button>
          </div>`).join('')}
      </div>
      ${scriptOpts ? `
      <div class="input-row">
        <select id="add-suite-script">${scriptOpts}</select>
        <button class="btn btn-sm btn-ghost" onclick="addSuiteScript('${id}')">Add</button>
      </div>` : ''}`
  }

  showModal('Edit Suite', renderBody(), [
    { label: 'Done', cls: 'btn-primary', action: () => { closeModal(); renderSuitesPage() } }
  ], suite.name)

  window._editSuiteId = id
  window._editSuiteScripts = suiteScripts
  window._editAllScripts = allScripts
  window._qcModalCleanupHook = () => {
    window._editSuiteId = null
    window._editSuiteScripts = null
    window._editAllScripts = null
  }

  // Drag-and-drop reordering
  const list = document.getElementById('suite-script-list')
  if (list) {
    let dragEl = null
    list.addEventListener('dragstart', e => {
      dragEl = e.target.closest('.suite-script-row')
      if (!dragEl) return
      dragEl.classList.add('dragging')
      e.dataTransfer.effectAllowed = 'move'
    })
    list.addEventListener('dragover', e => {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      const target = e.target.closest('.suite-script-row')
      if (!target || target === dragEl) return
      const rect = target.getBoundingClientRect()
      const mid = rect.top + rect.height / 2
      if (e.clientY < mid) {
        list.insertBefore(dragEl, target)
      } else {
        list.insertBefore(dragEl, target.nextSibling)
      }
    })
    list.addEventListener('dragend', async () => {
      if (!dragEl) return
      dragEl.classList.remove('dragging')
      dragEl = null
      // Update order numbers
      const rows = list.querySelectorAll('.suite-script-row')
      const scriptIds = []
      rows.forEach((row, i) => {
        row.querySelector('.suite-script-order').textContent = i + 1
        scriptIds.push(row.dataset.scriptId)
      })
      // Save new order
      const res = await api('PUT', '/suites/' + id + '/order', { script_ids: scriptIds })
      if (res.ok === false) toast(res.error, 'error')
      else {
        // Update local state so modal re-renders keep the new order
        window._editSuiteScripts = scriptIds.map((sid, i) => {
          const s = suiteScripts.find(x => x.script_id === sid)
          return { ...s, order_index: i }
        })
      }
    })
  }
}

async function renameSuite(suiteId) {
  const newName = document.getElementById('edit-suite-name').value.trim()
  if (!newName) return
  const res = await api('PUT', '/suites/' + suiteId, { name: newName })
  if (res.ok === false) { toast(res.error, 'error'); return }
  toast('Suite renamed')
  editSuiteModal(suiteId)
}

async function addSuiteScript(suiteId) {
  const sel = document.getElementById('add-suite-script')
  if (!sel || !sel.value) return
  const res = await api('POST', '/suites/' + suiteId + '/scripts', { script_id: sel.value })
  if (res.ok === false) { toast(res.error, 'error'); return }
  editSuiteModal(suiteId)
}

async function removeSuiteScript(suiteId, scriptId) {
  const res = await api('DELETE', '/suites/' + suiteId + '/scripts/' + scriptId)
  if (res.ok === false) { toast(res.error, 'error'); return }
  editSuiteModal(suiteId)
}

async function runSuiteModal(id, name) {
  const envsRes = await api('GET', '/envs')
  const envs = envsRes.environments || []

  showModal('Run Suite', `
    <div class="form-group">
      <label class="form-label">Environment (optional)</label>
      <select id="run-env">
        <option value="">None</option>
        ${envs.map(e => `<option value="${e.name}">${escHtml(e.name)}</option>`).join('')}
      </select>
    </div>
    <div style="display:flex;gap:12px">
      <div class="form-group" style="flex:1">
        <label class="form-label">Browser</label>
        <select id="run-browser">
          <option value="chromium" selected>Chromium</option>
          <option value="firefox">Firefox</option>
          <option value="webkit">WebKit</option>
        </select>
      </div>
      <div class="form-group" style="flex:1">
        <label class="form-label">Resolution</label>
        <select id="run-resolution">
          <option value="">Default</option>
          <option value="1920x1080">1920x1080</option>
          <option value="1366x768">1366x768</option>
          <option value="1280x720">1280x720</option>
          <option value="390x844">390x844 (Mobile)</option>
        </select>
      </div>
    </div>
    <div style="display:flex;gap:16px">
      <label class="checkbox-wrap">
        <input type="checkbox" id="run-headless">
        Headless
      </label>
      <label class="checkbox-wrap">
        <input type="checkbox" id="run-stop-on-fail">
        Stop on first failure
      </label>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Run Suite', cls: 'btn-primary', action: async () => {
      const env_name = document.getElementById('run-env').value || undefined
      const stop_on_fail = document.getElementById('run-stop-on-fail').checked
      const browser = document.getElementById('run-browser').value
      const resolution = document.getElementById('run-resolution').value || undefined
      const headless = document.getElementById('run-headless').checked
      // Show spinner
      document.querySelector('.modal-body').innerHTML = `
        <div class="loading-state">
          <div class="spinner spinner-lg"></div>
          <p>Running suite...</p>
        </div>`
      document.querySelector('.modal-footer').innerHTML = ''

      const res = await api('POST', '/runs', { suite_id: id, env_name, stop_on_fail, browser, resolution, headless })
      if (res.ok === false) {
        document.querySelector('.modal-body').innerHTML = `<p style="color:var(--danger)">${escHtml(res.error)}</p>`
        return
      }
      showRunResults(res.run || res, name)
    }}
  ], name)
}

function showRunResults(run, suiteName) {
  const scripts = run.scripts || []
  const skipped = run.skipped || 0
  const statusBadge = run.status === 'PASSED'
    ? '<span class="badge badge-success"><span class="badge-dot"></span>PASSED</span>'
    : '<span class="badge badge-danger"><span class="badge-dot"></span>FAILED</span>'

  const body = `
    <div class="stats-row">
      <div class="stat-card"><div class="stat-value">${run.total || 0}</div><div class="stat-label">Total</div></div>
      <div class="stat-card"><div class="stat-value pass">${run.passed || 0}</div><div class="stat-label">Passed</div></div>
      <div class="stat-card"><div class="stat-value fail">${run.failed || 0}</div><div class="stat-label">Failed</div></div>
      <div class="stat-card"><div class="stat-value">${skipped}</div><div class="stat-label">Skipped</div></div>
    </div>
    ${scripts.map(s => {
      const cls = s.status === 'PASSED' ? 'pass' : s.status === 'FAILED' ? 'fail' : 'skip'
      const badge = s.status === 'PASSED'
        ? '<span class="badge badge-success"><span class="badge-dot"></span>PASSED</span>'
        : s.status === 'FAILED'
        ? '<span class="badge badge-danger"><span class="badge-dot"></span>FAILED</span>'
        : '<span class="badge badge-neutral">SKIPPED</span>'
      const errorId = 'err-' + Math.random().toString(36).slice(2, 8)
      const traceId = 'trace-' + Math.random().toString(36).slice(2, 8)

      // Extract friendly error (last line of traceback)
      let friendlyError = ''
      let fullTrace = ''
      if (s.status === 'FAILED' && s.error_message) {
        const lines = s.error_message.trim().split('\n')
        friendlyError = lines[lines.length - 1] || ''
        fullTrace = s.error_message
      }

      // Screenshot block
      let screenshotBlock = ''
      if (s.screenshot_path) {
        const filename = s.screenshot_path.split(/[\\/]/).pop()
        screenshotBlock = `<div class="script-result-screenshot">
          <img src="/api/screenshots/${encodeURIComponent(filename)}" alt="Failure screenshot"
               onclick="window.open(this.src, '_blank')" />
        </div>`
      }

      // Console/network detail blocks
      let diagnosticsBlock = ''
      const consoleLogs = s.console_log ? (() => { try { return JSON.parse(s.console_log) } catch { return [] } })() : []
      const networkLogs = s.network_log ? (() => { try { return JSON.parse(s.network_log) } catch { return [] } })() : []

      if (consoleLogs.length > 0 || networkLogs.length > 0) {
        const diagId = 'diag-' + Math.random().toString(36).slice(2, 8)
        let details = ''
        if (consoleLogs.length > 0) {
          details += '<div class="diag-section-label">Console</div>'
          details += consoleLogs.map(c =>
            `<div class="diag-entry diag-console"><span class="diag-type">${escHtml(c.type)}</span> ${escHtml(c.text)}</div>`
          ).join('')
        }
        if (networkLogs.length > 0) {
          details += '<div class="diag-section-label">Network Failures</div>'
          details += networkLogs.map(n =>
            `<div class="diag-entry diag-network"><span class="diag-type">${escHtml(n.method)}</span> ${escHtml(n.url)}${n.failure ? ' — ' + escHtml(n.failure) : ''}</div>`
          ).join('')
        }
        diagnosticsBlock = `<div class="script-result-diagnostics">
          <div class="script-result-error-toggle" onclick="document.getElementById('${diagId}').classList.toggle('collapsed')">
            <span class="script-result-error-label" style="color: var(--text-warning, #e6a700)">Diagnostics</span>
            <span class="script-result-error-chevron">&#9662;</span>
          </div>
          <div id="${diagId}" class="script-result-error-body collapsed">
            <div class="diag-details">${details}</div>
          </div>
        </div>`
      }

      // Error block with friendly message + collapsible full traceback
      const errorBlock = s.status === 'FAILED' && friendlyError
        ? `<div class="script-result-error">
            <div class="script-result-friendly-error">${escHtml(friendlyError)}</div>
            ${screenshotBlock}
            <div class="script-result-error-toggle" onclick="document.getElementById('${traceId}').classList.toggle('collapsed')">
              <span class="script-result-error-label">Full Traceback</span>
              <span class="script-result-error-chevron">&#9662;</span>
            </div>
            <div id="${traceId}" class="script-result-error-body collapsed">
              <pre class="script-result-error-msg">${escHtml(fullTrace)}</pre>
            </div>
          </div>`
        : ''
      return `
      <div class="script-result-card ${cls}">
        <div class="script-result-card-top">
          <div>
            <div class="script-result-name">${escHtml(s.name)}</div>
            <div class="script-result-meta">
              <span>Duration: ${s.duration_ms != null ? s.duration_ms + ' ms' : '\u2014'}</span>
              ${(s.console_errors || 0) > 0 ? '<span class="meta-warn">Console errors: ' + (s.console_errors || 0) + '</span>' : '<span>Console errors: 0</span>'}
              ${(s.network_failures || 0) > 0 ? '<span class="meta-warn">Net failures: ' + (s.network_failures || 0) + '</span>' : '<span>Net: 0</span>'}
            </div>
          </div>
          ${badge}
        </div>
        ${errorBlock}
        ${diagnosticsBlock}
      </div>`
    }).join('')}`

  showModal('Execution History', body, [
    { label: 'Close', cls: 'btn-ghost', action: () => { closeModal(); renderSuitesPage() } }
  ], suiteName + ' \u00b7 ' + statusBadge)
}

async function deleteSuite(id, name) {
  showModal('Delete Suite', `
    <p>Delete suite <strong>"${name}"</strong>?</p>
    <p class="text-muted mt-4">This will not delete the scripts themselves.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Delete', cls: 'btn-danger', action: async () => {
      const res = await api('DELETE', '/suites/' + id)
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Suite deleted')
      renderSuitesPage()
    }}
  ])
}

// ── Runs Page ───────────────────────────────────────────────────

async function renderRunsPage() {
  const page = document.getElementById('page-content')
  if (!state.activeProject) { renderNoProject(page); return }

  const res = await api('GET', '/runs')
  const runs = res.runs || []

  page.innerHTML = `
    <div class="page-header">
      <div class="page-header-text">
        <h2>Regression Runs</h2>
        <p>View execution history</p>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Run ID</th>
          <th>Suite</th>
          <th>Status</th>
          <th>Results</th>
          <th>Started</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${runs.length === 0
            ? `<tr><td colspan="6"><div class="empty-state"><div class="empty-state-icon">\u25B6</div><p>No runs yet.<br>Run a suite to see results here.</p></div></td></tr>`
            : runs.map(r => `
            <tr>
              <td class="mono">${escHtml(r.id)}</td>
              <td>${escHtml(r.suite_name)}</td>
              <td><span class="badge ${r.status==='PASSED'?'badge-success':'badge-danger'}"><span class="badge-dot"></span>${r.status}</span></td>
              <td class="text-sm">${r.passed}/${r.total} passed${r.failed ? ', ' + r.failed + ' failed' : ''}</td>
              <td class="text-muted text-sm">${fmtDate(r.started_at)}</td>
              <td><div class="table-actions">
                <button class="btn btn-xs btn-ghost" onclick="viewRunModal('${r.id}','${escHtml(r.suite_name)}')">View</button>
              </div></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`
}

async function viewRunModal(id, suiteName) {
  const res = await api('GET', '/runs/' + id)
  if (res.ok === false) { toast(res.error, 'error'); return }
  showRunResults(res.run || res, suiteName)
}

// ── Environments Page ───────────────────────────────────────────

async function renderEnvsPage() {
  const page = document.getElementById('page-content')
  if (!state.activeProject) { renderNoProject(page); return }

  const res = await api('GET', '/envs')
  const envs = res.environments || []

  page.innerHTML = `
    <div class="page-header">
      <div class="page-header-text">
        <h2>Environments</h2>
        <p>Manage environment variables</p>
      </div>
      <button class="btn btn-primary" onclick="createEnvModal()">+ New Environment</button>
    </div>
    <div id="env-cards">
      ${envs.length === 0
        ? `<div class="empty-state"><div class="empty-state-icon">\u2699</div><p>No environments yet.</p></div>`
        : envs.map(e => `<div id="env-card-${escHtml(e.name)}" class="env-card"></div>`).join('')}
    </div>`

  for (const e of envs) {
    await renderEnvCard(e.name)
  }
}

function _envVarRowHTML(key, value, isSecret, isMasked, envName) {
  // isMasked=true means the value shown is a placeholder for a stored secret.
  // We tag the row so the collector knows to send {unchanged:true} unless the user edits.
  const maskedAttr = isMasked ? ' data-masked="1"' : ''
  const envAttr = envName ? ` data-env-name="${escHtml(envName)}"` : ''
  return `
    <tr${maskedAttr}${envAttr}>
      <td style="width:30%"><input type="text" class="env-row-key" value="${escHtml(key)}" placeholder="KEY"></td>
      <td><input type="${isSecret ? 'password' : 'text'}" class="env-row-value" value="${escHtml(value)}" placeholder="value" oninput="_onEnvValueEdit(this)" onfocus="_onEnvValueFocus(this)"></td>
      <td style="width:60px">
        <label class="checkbox-wrap" style="margin:0" title="Secret"><input type="checkbox" class="env-row-secret" ${isSecret ? 'checked' : ''} onchange="_onEnvSecretToggle(this)"> \uD83D\uDD12</label>
      </td>
      <td style="width:40px"><button class="btn btn-xs btn-outline-danger" onclick="this.closest('tr').remove()">\u2715</button></td>
    </tr>`
}

function _onEnvValueFocus(input) {
  // First focus on a masked secret clears the placeholder so typed input replaces it.
  const tr = input.closest('tr')
  if (tr && tr.dataset.masked === '1' && !tr.dataset.edited) {
    input.value = ''
  }
}

function _onEnvValueEdit(input) {
  const tr = input.closest('tr')
  if (!tr) return
  tr.dataset.edited = '1'
  delete tr.dataset.masked
}

async function _onEnvSecretToggle(cb) {
  const tr = cb.closest('tr')
  if (!tr) return
  const valInput = tr.querySelector('.env-row-value')
  if (!valInput) return

  // Un-ticking a stored-masked secret: fetch decrypted value so the user sees it.
  // Only fetch when the row is still "masked" — if the user already typed a new
  // plaintext, we must not overwrite their input.
  if (!cb.checked && tr.dataset.masked === '1') {
    const envName = tr.dataset.envName
    const keyInput = tr.querySelector('.env-row-key')
    const key = keyInput ? keyInput.value.trim() : ''
    if (envName && key) {
      try {
        const res = await api('GET', '/envs/' + encodeURIComponent(envName) + '/vars/' + encodeURIComponent(key) + '/reveal')
        if (res && res.ok) {
          valInput.value = res.value || ''
        } else if (res && res.error) {
          toast(res.error, 'error')
        }
      } catch (e) {
        toast('Failed to reveal value', 'error')
      }
    }
  }

  valInput.type = cb.checked ? 'password' : 'text'
  // Toggling the checkbox means the user is redefining this value — no longer a stored-masked row.
  delete tr.dataset.masked
  tr.dataset.edited = '1'
}

function _addEnvVarRow(tableId) {
  const table = document.getElementById(tableId)
  if (!table) return
  table.insertAdjacentHTML('beforeend', _envVarRowHTML('', '', false))
  const rows = table.querySelectorAll('tr')
  rows[rows.length - 1].querySelector('.env-row-key')?.focus()
}

function _collectVarsFromTable(tableId) {
  const table = document.getElementById(tableId)
  if (!table) return []
  const vars = []
  table.querySelectorAll('tr').forEach(tr => {
    const key = tr.querySelector('.env-row-key')?.value.trim()
    const value = tr.querySelector('.env-row-value')?.value || ''
    const is_secret = tr.querySelector('.env-row-secret')?.checked ? 1 : 0
    if (!key) return
    // Masked secret left untouched: tell backend to keep the stored ciphertext as-is.
    if (is_secret && tr.dataset.masked === '1') {
      vars.push({ key, is_secret, unchanged: true })
    } else {
      vars.push({ key, value, is_secret })
    }
  })
  return vars
}

function toggleEnvCard(name) {
  const body = document.getElementById('env-body-' + name)
  const chevron = document.getElementById('env-chevron-' + name)
  if (!body) return
  const collapsed = body.classList.toggle('hidden')
  if (chevron) chevron.textContent = collapsed ? '\u25B6' : '\u25BC'
}

async function renderEnvCard(name) {
  const container = document.getElementById('env-card-' + name)
  if (!container) return

  const vars = await api('GET', '/envs/' + encodeURIComponent(name))
  const varList = vars.variables || []
  const tableId = 'env-table-' + name

  container.innerHTML = `
    <div class="env-card-header" style="cursor:pointer" onclick="toggleEnvCard('${escHtml(name)}')">
      <div style="display:flex;align-items:center;gap:8px">
        <span id="env-chevron-${escHtml(name)}" style="font-size:10px;color:var(--text-secondary)">\u25B6</span>
        <span class="env-name">${escHtml(name)}</span>
        <span class="badge badge-neutral">${varList.length} vars</span>
      </div>
      <button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation(); deleteEnv('${escHtml(name)}')">Delete</button>
    </div>
    <div id="env-body-${escHtml(name)}" class="hidden">
      <div style="padding:12px 20px">
        <table class="env-vars-table" id="${escHtml(tableId)}">
          ${varList.map(v => _envVarRowHTML(v.key, v.value, v.is_secret, !!v.is_secret, name)).join('')}
        </table>
      </div>
      <div class="env-footer">
        <div>
          <button class="btn btn-sm btn-ghost" onclick="_addEnvVarRow('${escHtml(tableId)}')">+ Add Row</button>
          <button class="btn btn-sm btn-ghost" onclick="copyEnvModal('${escHtml(name)}')">Copy Env</button>
        </div>
        <div>
          <button class="btn btn-sm btn-primary" onclick="saveEnvVarsBulk('${escHtml(name)}', '${escHtml(tableId)}')">Save</button>
        </div>
      </div>
    </div>`
}

function createEnvModal() {
  const tableId = 'new-env-vars-table'
  const rows = _envVarRowHTML('', '', false).repeat(4)
  showModal('Create Environment', `
    <div class="form-group">
      <label class="form-label">Environment Name</label>
      <input type="text" id="new-env-name" placeholder="e.g. staging" autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Variables</label>
      <table class="env-vars-table" id="${tableId}">
        ${rows}
      </table>
      <button class="btn btn-sm btn-ghost" style="margin-top:8px" onclick="_addEnvVarRow('${tableId}')">+ Add Row</button>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Create', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('new-env-name').value.trim()
      if (!name) { toast('Environment name is required', 'error'); return }
      const res = await api('POST', '/envs', { name })
      if (res.ok === false) { toast(res.error, 'error'); return }
      const vars = _collectVarsFromTable(tableId)
      if (vars.length > 0) {
        const bulkRes = await api('POST', '/envs/' + encodeURIComponent(name) + '/vars', { vars })
        if (bulkRes.ok === false) { toast(bulkRes.error, 'error'); return }
      }
      closeModal(); toast('Environment "' + name + '" created')
      renderEnvsPage()
    }}
  ])
}

async function saveEnvVarsBulk(envName, tableId) {
  const vars = _collectVarsFromTable(tableId)
  const res = await api('POST', '/envs/' + encodeURIComponent(envName) + '/vars', { vars })
  if (res.ok === false) { toast(res.error, 'error'); return }
  toast('Variables saved')
  renderEnvsPage()
}

function copyEnvModal(envName) {
  showModal('Copy Environment', `
    <p>Copy all variables from <strong>"${escHtml(envName)}"</strong> to a new environment.</p>
    <div class="form-group" style="margin-top:12px">
      <label class="form-label">New Environment Name</label>
      <input type="text" id="copy-env-name" placeholder="e.g. production" autofocus>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Copy', cls: 'btn-primary', action: async () => {
      const newName = document.getElementById('copy-env-name').value.trim()
      if (!newName) { toast('Environment name is required', 'error'); return }
      const res = await api('POST', '/envs/' + encodeURIComponent(envName) + '/copy', { new_name: newName })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Environment copied as "' + newName + '"')
      renderEnvsPage()
    }}
  ])
}

async function deleteEnv(name) {
  showModal('Delete Environment', `
    <p>Delete environment <strong>"${name}"</strong> and all its variables?</p>
    <p class="text-muted mt-4">This action cannot be undone.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Delete', cls: 'btn-danger', action: async () => {
      const res = await api('DELETE', '/envs/' + encodeURIComponent(name))
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Environment deleted')
      renderEnvsPage()
    }}
  ])
}
