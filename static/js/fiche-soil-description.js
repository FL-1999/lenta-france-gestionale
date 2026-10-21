document.addEventListener('DOMContentLoaded', () => {
  const rows = document.getElementById('strati-container');
  if (!rows) return;
  function sync(row) {
    const choice = row.querySelector('[name="strato_descrizione"]');
    const input = row.querySelector('[name="strato_descrizione_altro"]');
    if (!choice || !input) return;
    const other = choice.value === 'altro';
    input.closest('label').hidden = !other;
    input.style.removeProperty('display');
    input.required = other;
    if (!other) input.value = '';
  }
  const refresh = () => rows.querySelectorAll('.strato-row').forEach(sync);
  rows.addEventListener('change', event => {
    if (event.target.matches('[data-soil-description]')) sync(event.target.closest('.strato-row'));
  });
  new MutationObserver(refresh).observe(rows, {childList: true});
  refresh();
});
