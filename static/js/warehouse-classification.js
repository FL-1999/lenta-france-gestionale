(() => {
  const form = document.getElementById('classification-form');
  if (!form) return;
  function update() {
    const mode = form.elements.mode.value;
    form.querySelectorAll('[data-classification-mode]').forEach(group => {
      const active = group.dataset.classificationMode === mode;
      group.hidden = !active;
      group.querySelectorAll('input,select').forEach(field => {
        field.disabled = !active;
        field.required = active;
      });
    });
    const freshMacro = mode === 'new' && form.elements.macro_id.value === '__new__';
    form.querySelector('[data-new-macro]').hidden = !freshMacro;
    form.elements.macro_name.disabled = !freshMacro;
    form.elements.macro_name.required = freshMacro;
  }
  form.addEventListener('change', update);
  update();
})();
