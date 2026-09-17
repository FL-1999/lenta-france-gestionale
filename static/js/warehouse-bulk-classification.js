(() => {
  const form = document.getElementById('warehouse-bulk-classification');
  if (!form) return;
  const boxes = [...form.querySelectorAll('input[name=item_ids]')];
  const all = form.querySelector('[data-select-all]');
  const destination = form.querySelector('[name=category_id]');
  const submit = form.querySelector('button[type=submit]');
  function update() {
    const count = boxes.filter(box => box.checked).length;
    form.querySelector('[data-selected-count]').textContent = count;
    all.checked = count === boxes.length && count > 0;
    all.indeterminate = count > 0 && count < boxes.length;
    submit.disabled = count === 0 || !destination.value;
    boxes.forEach(box => box.closest('.warehouse-row').classList.toggle('is-selected', box.checked));
  }
  all.addEventListener('change', () => { boxes.forEach(box => { box.checked = all.checked; }); update(); });
  form.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
})();
