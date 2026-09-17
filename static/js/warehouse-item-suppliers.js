(() => {
  const rows = document.getElementById('article-suppliers');
  const template = document.getElementById('article-supplier-template');
  if (!rows || !template) return;
  function validateRow(row) {
    const supplier = row.querySelector('select');
    const code = row.querySelector('input');
    supplier.required = !!code.value.trim();
    code.required = !!supplier.value;
  }
  rows.querySelectorAll('[data-supplier-row]').forEach(validateRow);
  document.getElementById('add-article-supplier').addEventListener('click', () => {
    rows.append(template.content.cloneNode(true));
    rows.lastElementChild.querySelector('select').focus();
  });
  rows.addEventListener('input', e => validateRow(e.target.closest('[data-supplier-row]')));
  rows.addEventListener('change', e => validateRow(e.target.closest('[data-supplier-row]')));
  rows.addEventListener('click', e => {
    const remove = e.target.closest('[data-remove-supplier]');
    if (remove) {
      remove.closest('[data-supplier-row]').remove();
      document.getElementById('add-article-supplier').focus();
    }
  });
})();
