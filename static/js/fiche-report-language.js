// GET-only language selection: preview and downloads use the same document language.
document.querySelectorAll('[data-report-language-form]').forEach(form => {
  form.querySelector('select').addEventListener('change', () => form.requestSubmit());
});
