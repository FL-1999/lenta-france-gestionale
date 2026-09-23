(() => {
  const form = document.getElementById('archive-actions');
  const all = document.getElementById('archive-select-all');
  if (!form || !all) return;
  const boxes = [...form.querySelectorAll('input[name="asset_ids"]:not(:disabled)')];
  const buttons = [...form.querySelectorAll('button[name="action"]')];
  function update() {
    const selected = boxes.filter(box => box.checked).length;
    all.checked = boxes.length > 0 && selected === boxes.length;
    all.indeterminate = selected > 0 && selected < boxes.length;
    all.disabled = boxes.length === 0;
    buttons.forEach(button => { button.disabled = selected === 0; });
  }
  all.addEventListener('change', () => {
    boxes.forEach(box => { box.checked = all.checked; });
    update();
  });
  boxes.forEach(box => box.addEventListener('change', update));
  update();
})();
