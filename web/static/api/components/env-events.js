/**
 * Shared "collection environment changed" signal.
 *
 * A collection's bound environment lives in one place (api_collections.env_name),
 * but several views can show or change it at once — the request-editor header
 * selector, the collection-detail selector, the collection-settings drawer.
 * They stay consistent by all listening to one document-level CustomEvent:
 * whoever performs the bind (via createEnvSelector) emits, everyone else updates.
 */
const EVT = 'qc:collection-env-changed';

export function emitEnvChanged(collectionId, envName) {
  document.dispatchEvent(new CustomEvent(EVT, {
    detail: { collectionId: collectionId == null ? null : String(collectionId), envName: envName || null },
  }));
}

/**
 * Subscribe to env changes. Returns an unsubscribe function — call it when the
 * subscribing view is torn down so stale handlers don't pile up.
 */
export function onEnvChanged(handler) {
  const fn = (e) => handler(e.detail || {});
  document.addEventListener(EVT, fn);
  return () => document.removeEventListener(EVT, fn);
}
