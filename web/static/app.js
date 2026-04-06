// ── State & Router ──────────────────────────────────────────────

const state = {
  activeProject: null,
  page: 'scripts',
  authenticated: false,
  user: null,
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

  const res = await api('GET', '/projects/active')
  if (res.id) state.activeProject = { id: res.id, name: res.name }
  renderSidebar()
  renderTopbar()
  await routes[state.page]()

  // Close dropdowns on outside click
  document.addEventListener('click', (e) => {
    const wrap = document.getElementById('project-switcher-wrap')
    if (wrap && !wrap.contains(e.target)) {
      const dd = document.getElementById('project-dropdown')
      if (dd) dd.classList.add('hidden')
    }
  })
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
    </div>`
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

function showModal(title, bodyHTML, buttons = [], subtitle = '') {
  const backdrop = document.getElementById('modal-backdrop')
  const root = document.getElementById('modal-root')

  const btns = buttons.map((b, i) =>
    `<button class="btn btn-sm ${b.cls}" data-btn-idx="${i}">${escHtml(b.label)}</button>`
  ).join('')

  root.innerHTML = `
    <div class="modal-card">
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
  document.getElementById('modal-backdrop').classList.add('hidden')
  document.getElementById('modal-root').classList.add('hidden')
  document.getElementById('modal-root').innerHTML = ''
  document.getElementById('modal-backdrop').onclick = null
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

  document.addEventListener('click', (e) => {
    const wrap = document.getElementById('project-switcher-wrap')
    if (wrap && !wrap.contains(e.target)) {
      const dd = document.getElementById('project-dropdown')
      if (dd) dd.classList.add('hidden')
    }
  })

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

function recordScriptModal() {
  const features = window._features || []
  if (features.length === 0) { toast('Create a feature first', 'error'); return }
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
      <label class="form-label">Start URL (optional)</label>
      <input type="text" id="rec-url" placeholder="e.g. https://myapp.com">
    </div>
    <p class="text-muted">A browser will open for recording. Interact with your app, then close the browser when done.</p>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Start Recording', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('rec-name').value.trim()
      const feature_id = document.getElementById('rec-feature').value
      const url = document.getElementById('rec-url').value.trim()
      if (!name || !feature_id) { toast('Name and feature required', 'error'); return }

      document.querySelector('.modal-body').innerHTML = `
        <div class="loading-state">
          <div class="spinner spinner-lg"></div>
          <p>Recording in progress...<br><span class="text-muted">Close the browser when done.</span></p>
        </div>`
      document.querySelector('.modal-footer').innerHTML = ''

      const res = await api('POST', '/scripts/record', { name, feature_id, url: url || undefined })
      if (res.ok === false) { closeModal(); toast(res.error, 'error'); return }
      closeModal(); toast('Script "' + name + '" recorded')
      renderScriptsPage()
    }}
  ])
}

function createScriptModal() {
  const features = window._features || []
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
      <label class="form-label">Script Content</label>
      <textarea id="script-content" placeholder="from playwright.sync_api import sync_playwright&#10;&#10;with sync_playwright() as p:&#10;    browser = p.chromium.launch()&#10;    ..."></textarea>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Create Script', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('script-name').value.trim()
      const feature_id = document.getElementById('script-feature').value
      const content = document.getElementById('script-content').value
      if (!name || !feature_id) { toast('Name and feature required', 'error'); return }
      const res = await api('POST', '/scripts', { name, feature_id, content })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Script "' + name + '" created')
      renderScriptsPage()
    }}
  ])
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
    <div class="form-group">
      <label class="form-label">Content</label>
      <textarea readonly style="min-height:200px;background:var(--bg-base);cursor:default">${escHtml(s.content || '')}</textarea>
    </div>`, [
    { label: 'Close', cls: 'btn-ghost', action: closeModal }
  ], 'Script ID: ' + s.id)
}

async function editScriptModal(id) {
  const sRes = await api('GET', '/scripts/' + id)
  if (sRes.ok === false) { toast(sRes.error, 'error'); return }
  const s = sRes.script || sRes
  const features = window._features || []
  showModal('Edit Script', `
    <div class="form-group">
      <label class="form-label">Script Name</label>
      <input type="text" id="edit-script-name" value="${escHtml(s.name)}">
    </div>
    <div class="form-group">
      <label class="form-label">Content</label>
      <textarea id="edit-script-content" style="min-height:200px">${escHtml(s.content || '')}</textarea>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Save', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('edit-script-name').value.trim()
      const content = document.getElementById('edit-script-content').value
      if (!name) return
      const res = await api('PUT', '/scripts/' + id, { name, content })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Script updated')
      renderScriptsPage()
    }}
  ], 'Script ID: ' + s.id)
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
          <th>Scripts</th>
          <th>Last Run</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${suites.length === 0
            ? `<tr><td colspan="4"><div class="empty-state"><div class="empty-state-icon">\u25A6</div><p>No suites yet.</p></div></td></tr>`
            : suites.map(s => `
            <tr>
              <td><strong>${escHtml(s.name)}</strong></td>
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
        const filename = s.screenshot_path.split('/').pop()
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
    </div>
    <div class="create-env-form">
      <div class="form-group" style="margin-bottom:0;flex:1">
        <label class="form-label">New Environment</label>
        <input type="text" id="new-env-name" placeholder="e.g. staging">
      </div>
      <button class="btn btn-primary" onclick="createEnv()">Create</button>
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

async function renderEnvCard(name) {
  const container = document.getElementById('env-card-' + name)
  if (!container) return

  const vars = await api('GET', '/envs/' + encodeURIComponent(name))
  const varList = vars.variables || []

  container.innerHTML = `
    <div class="env-card-header">
      <span class="env-name">${escHtml(name)}</span>
      <span class="badge badge-neutral">${varList.length} vars</span>
    </div>
    <div style="padding:12px 20px">
      <table class="env-vars-table">
        ${varList.map(v => `
        <tr data-key="${escHtml(v.key)}">
          <td style="width:30%"><input type="text" value="${escHtml(v.key)}" readonly style="cursor:default;opacity:0.7"></td>
          <td><input type="${v.is_secret ? 'password' : 'text'}" value="${escHtml(v.value)}" data-env="${escHtml(name)}" data-var-key="${escHtml(v.key)}" onchange="saveEnvVar(this,'${escHtml(name)}','${escHtml(v.key)}')"></td>
          <td style="width:40px"><button class="btn btn-xs btn-outline-danger" onclick="deleteEnvVar('${escHtml(name)}','${escHtml(v.key)}')">\u2715</button></td>
        </tr>`).join('')}
      </table>
    </div>
    <div class="env-footer">
      <button class="btn btn-sm btn-ghost" onclick="addEnvVarModal('${escHtml(name)}')">+ Add Variable</button>
      <button class="btn btn-sm btn-outline-danger" onclick="deleteEnv('${escHtml(name)}')">Delete Environment</button>
    </div>`
}

async function createEnv() {
  const name = document.getElementById('new-env-name').value.trim()
  if (!name) return
  const res = await api('POST', '/envs', { name })
  if (res.ok === false) { toast(res.error, 'error'); return }
  toast('Environment "' + name + '" created')
  renderEnvsPage()
}

function addEnvVarModal(envName) {
  showModal('Add Variable', `
    <div class="form-group">
      <label class="form-label">Key</label>
      <input type="text" id="var-key" placeholder="e.g. BASE_URL" autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Value</label>
      <input type="text" id="var-value" placeholder="e.g. https://staging.example.com">
    </div>
    <label class="checkbox-wrap">
      <input type="checkbox" id="var-secret">
      Secret (masked in UI)
    </label>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Add Variable', cls: 'btn-primary', action: async () => {
      const key = document.getElementById('var-key').value.trim()
      const value = document.getElementById('var-value').value
      const is_secret = document.getElementById('var-secret').checked
      if (!key) return
      const res = await api('POST', '/envs/' + encodeURIComponent(envName) + '/vars', { key, value, is_secret })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal(); toast('Variable added')
      renderEnvsPage()
    }}
  ], envName)
}

async function saveEnvVar(input, envName, key) {
  const value = input.value
  const res = await api('POST', '/envs/' + encodeURIComponent(envName) + '/vars', { key, value })
  if (res.ok === false) { toast(res.error, 'error'); return }
  toast('Variable updated')
}

async function deleteEnvVar(envName, key) {
  const res = await api('DELETE', '/envs/' + encodeURIComponent(envName) + '/vars/' + encodeURIComponent(key))
  if (res.ok === false) { toast(res.error, 'error'); return }
  toast('Variable deleted')
  renderEnvsPage()
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
