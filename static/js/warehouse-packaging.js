(() => {
  'use strict';
  const form = document.querySelector('#warehouse-item-form');
  if (!form) return;
  const enabled = form.elements.packaging_enabled;
  const base = form.elements.unita_misura;
  const kind = form.elements.packaging_kind;
  const stockUnit = form.elements.stock_unit;
  const stock = form.elements.quantita_disponibile;
  const fr = form.dataset.lang === 'fr';
  const labels = fr ? {bancale:'palettes', sacco:'sacs', kg:'kg', rotolo:'rouleaux', m:'mètres'} : {bancale:'bancali', sacco:'sacchi', kg:'kg', rotolo:'rotoli', m:'metri'};
  const fmt = n => new Intl.NumberFormat(fr ? 'fr-FR' : 'it-IT', {maximumFractionDigits:4, useGrouping:true}).format(n);
  let lastBase = base.value;
  function refresh(event) {
    if ((event?.target === base || event?.target === enabled) && ['m','rotolo'].includes(base.value)) kind.value = 'rotoli';
    if (event?.target === base && ['kg','sacco'].includes(base.value)) kind.value = 'sacchi';
    const roll = kind.value === 'rotoli';
    const units = roll ? ['bancale','rotolo','m'] : ['bancale','sacco','kg'];
    const count = form.elements[roll ? 'rotoli_per_bancale' : 'sacchi_per_bancale'];
    const amount = form.elements[roll ? 'metri_per_rotolo' : 'kg_per_sacco'];
    if ([enabled,kind].includes(event?.target) && enabled.checked && !units.includes(base.value) && base.tagName === 'SELECT') base.value = roll ? 'm' : 'sacco';
    const validBase = units.includes(base.value);
    if (event?.target === base && !validBase) enabled.checked = false;
    const active = enabled.checked;
    form.querySelector('[data-packaging-fields]').hidden = !active;
    for (const group of form.querySelectorAll('[data-packaging-kind]')) {
      const visible = active && group.dataset.packagingKind === kind.value;
      group.hidden = !visible;
      for (const field of group.querySelectorAll('input')) { field.disabled = !visible; field.required = visible; }
    }
    let selected = stockUnit.value || stockUnit.dataset.selected || base.value;
    if (lastBase !== base.value) selected = base.value;
    const options = active && validBase ? [base.value, ...units.filter(u => u !== base.value)] : [base.value];
    stockUnit.replaceChildren(...options.map(unit => new Option(labels[unit] || unit, unit)));
    stockUnit.value = options.includes(selected) ? selected : base.value;
    lastBase = base.value;
    for (const el of form.querySelectorAll('[data-base-unit]')) el.textContent = base.value;
    const b = Number(count.value), w = Number(amount.value), q = Number(stock.value);
    const valid = active && validBase && b > 0 && Number.isInteger(b) && w > 0 && Number.isFinite(b*w);
    form.querySelector('[data-packaging-preview]').textContent = valid
      ? `1 ${fr ? 'palette' : 'bancale'} = ${fmt(b)} ${labels[units[1]]} = ${fmt(b*w)} ${labels[units[2]]}`
      : (fr ? 'Renseignez la quantité par palette et par emballage.' : 'Inserisci il numero di confezioni per bancale e il contenuto di ogni confezione.');
    const output = form.querySelector('[data-stock-preview]');
    if (valid && stock.value !== '' && q >= 0 && Number.isFinite(q)) {
      const factors = {bancale:b*w, [units[1]]:w, [units[2]]:1};
      const total = q*factors[stockUnit.value];
      output.textContent = units.map(u => `${fmt(total/factors[u])} ${labels[u]}`).join(' = ');
    } else output.textContent = '';
  }
  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  refresh();
})();
