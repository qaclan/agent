/**
 * Discover Modal — stub (Task 14/15 will implement this).
 */
export function showDiscoverModal() {
  const existing = document.getElementById('api-discover-modal-stub');
  if (existing) { existing.remove(); return; }
  const el = document.createElement('div');
  el.id = 'api-discover-modal-stub';
  el.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center';
  el.innerHTML = '<div style="background:var(--bg-elevated,#131926);border:1px solid var(--border-default);border-radius:10px;padding:32px 40px;color:var(--text-primary,#fff);text-align:center"><p style="font-size:15px;font-weight:600;margin-bottom:8px">API Discovery</p><p style="font-size:13px;color:var(--text-muted,#94a3b8)">Coming soon.</p><button onclick="document.getElementById(\'api-discover-modal-stub\').remove()" style="margin-top:20px;padding:6px 18px;border-radius:6px;border:1px solid var(--border-default);background:none;color:var(--text-primary,#fff);cursor:pointer">Close</button></div>';
  document.body.appendChild(el);
  el.onclick = (e) => { if (e.target === el) el.remove(); };
}
