document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-fiche-form]'), root = document.querySelector('[data-fiche-soil]');
  const start = document.getElementById('quota_partenza'), coupe = document.getElementById('coupe_id');
  if (!form || !root || !start) return;
  const mode = document.getElementById('scavo_da_tn');
  const origin = () => SoilCoordinates.number(start.value);
  const datum = () => document.getElementById('fiche-panel-catalog')?.dataset.datum || coupe.selectedOptions[0]?.dataset.datum || 'NGF';
  const controller = SoilCoordinates.bind(root, {
    rows: document.getElementById('strati-container'), row: '.strato-row', start: '[data-strato-da]', end: '[data-strato-a]', origin, datum,
    material: row => {const select = row.querySelector('[name="strato_materiale"]');
      return select.value === 'altro' ? row.querySelector('[name="strato_materiale_altro"]').value : select.selectedOptions[0]?.textContent.trim();},
  });
  function refresh() {start.readOnly = mode?.value !== '0'; controller.refresh();}
  start.addEventListener('input', refresh); mode?.addEventListener('change', refresh);
  coupe?.addEventListener('change', () => {
    const option = coupe.selectedOptions[0];
    if (form.dataset.edit !== 'true') {
      mode.value = option?.dataset.scavo || '1';
      start.value = mode.value === '0' ? (option?.dataset.partenza || '') : (option?.dataset.quotaTn || '');
      start.dispatchEvent(new Event('input', {bubbles:true}));
    }
    refresh();
  });
  refresh();
});
