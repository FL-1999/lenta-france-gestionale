(() => {
  'use strict';
  const form = document.querySelector('#warehouse-item-form');
  if (!form) return;
  const enabled = form.elements.packaging_enabled;
  const base = form.elements.unita_misura;
  const bags = form.elements.sacchi_per_bancale;
  const weight = form.elements.kg_per_sacco;
  const stockUnit = form.elements.stock_unit;
  const stock = form.elements.quantita_disponibile;
  const fr = form.dataset.lang === 'fr';
  const units = ['bancale', 'sacco', 'kg'];
  const labels = fr ? {bancale:'palettes', sacco:'sacs', kg:'kg'} : {bancale:'bancali', sacco:'sacchi', kg:'kg'};
  const fmt = n => new Intl.NumberFormat(fr ? 'fr-FR' : 'it-IT', {maximumFractionDigits:4, useGrouping:true}).format(n);
  let lastBase = base.value;
  function refresh(event) {
    if (event?.target === enabled && enabled.checked && !units.includes(base.value) && base.tagName === 'SELECT') base.value = 'sacco';
    const validBase = units.includes(base.value);
    if (event?.target === base && !validBase) enabled.checked = false;
    const active = enabled.checked;
    form.querySelector('[data-packaging-fields]').hidden = !active;
    for (const field of [bags, weight]) { field.disabled = !active; field.required = active; }
    let selected = stockUnit.value || stockUnit.dataset.selected || base.value;
    if (lastBase !== base.value) selected = base.value;
    const options = active && validBase ? [base.value, ...units.filter(u => u !== base.value)] : [base.value];
    stockUnit.replaceChildren(...options.map(unit => new Option(labels[unit] || unit, unit)));
    stockUnit.value = options.includes(selected) ? selected : base.value;
    lastBase = base.value;
    for (const el of form.querySelectorAll('[data-base-unit]')) el.textContent = base.value;
    const b = Number(bags.value), w = Number(weight.value), q = Number(stock.value);
    const valid = active && validBase && b > 0 && Number.isInteger(b) && w > 0 && Number.isFinite(b*w);
    form.querySelector('[data-packaging-preview]').textContent = valid
      ? `1 ${fr ? 'palette' : 'bancale'} = ${fmt(b)} ${labels.sacco} = ${fmt(b*w)} kg`
      : (fr ? 'Renseignez le nombre de sacs et leur poids.' : 'Inserisci quanti sacchi contiene il bancale e il peso di ogni sacco.');
    const output = form.querySelector('[data-stock-preview]');
    if (valid && stock.value !== '' && q >= 0 && Number.isFinite(q)) {
      const factors = {bancale:b*w, sacco:w, kg:1};
      const kg = q*factors[stockUnit.value];
      output.textContent = units.map(u => `${fmt(kg/factors[u])} ${labels[u]}`).join(' = ');
    } else output.textContent = '';
  }
  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  refresh();
})();
