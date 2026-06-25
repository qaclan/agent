import { showHarImport } from './har-import-view.js';
import { showOpenApiImport } from './openapi-import-view.js';
import { showPostmanImport } from './postman-import-view.js';
import { showRecordApis } from './record-apis-view.js';

export function showDiscoverModal() {
  // Use the existing showModal from app.js (classic script, available as window.showModal)
  const options = [
    { icon: '⏺', title: 'Record APIs', desc: 'Live browser capture', action: showRecordApis },
    { icon: '📄', title: 'Import HAR', desc: 'Chrome DevTools HAR export', action: showHarImport },
    { icon: '📋', title: 'Import OpenAPI', desc: 'OpenAPI 3.x / Swagger 2.x', action: showOpenApiImport },
    { icon: '📮', title: 'Import Postman', desc: 'Postman Collection v2.1', action: showPostmanImport },
    { icon: '🟤', title: 'Import Bruno', desc: '.bru collection files', action: () => showBrunoImport() },
    { icon: '🎭', title: 'From Playwright Run', desc: 'Extract APIs from recorded runs', action: () => window._toast('Coming soon — extract APIs from Playwright recordings') },
  ];

  const grid = document.createElement('div');
  grid.className = 'discover-modal-grid';

  options.forEach(opt => {
    const card = document.createElement('div');
    card.className = 'discover-option-card';
    card.innerHTML = `
      <div class="discover-option-icon">${opt.icon}</div>
      <div class="discover-option-title">${opt.title}</div>
      <div class="discover-option-desc">${opt.desc}</div>`;
    card.onclick = () => {
      window.closeModal();
      opt.action();
    };
    grid.appendChild(card);
  });

  const container = document.createElement('div');
  container.appendChild(grid);

  window.showModal('Discover APIs', container.innerHTML, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
  ]);

  // Re-attach click handlers after modal renders
  requestAnimationFrame(() => {
    document.querySelectorAll('.discover-option-card').forEach((card, i) => {
      card.onclick = () => {
        window.closeModal();
        options[i].action();
      };
    });
  });
}

async function showBrunoImport() {
  const { showBrunoImportView } = await import('./postman-import-view.js');
  showBrunoImportView();
}
