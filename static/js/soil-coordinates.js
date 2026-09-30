/* Depths remain the saved values. Elevation inputs edit those same intervals. */
window.SoilCoordinates = (() => {
  const fr = document.documentElement.lang === 'fr';
  const t = (it, french) => fr ? french : it;
  const number = value => String(value ?? '').trim() === '' ? null :
    (Number.isFinite(Number(String(value).replace(',', '.'))) ? Number(String(value).replace(',', '.')) : null);
  const format = value => value === null ? '—' : value.toFixed(2);
  function bind(root, options) {
    if (root.soilCoordinates) return root.soilCoordinates;
    root.querySelectorAll('[data-soil-coordinate-ui], [data-soil-elevation]').forEach(el => el.remove());
    const toolbar = document.createElement('div'); toolbar.dataset.soilCoordinateUi = '';
    toolbar.className = 'soil-coordinate-toolbar';
    const label = document.createElement('label'); label.textContent = t('Inserisci gli strati in', 'Saisir les couches en');
    const mode = document.createElement('select'); mode.className = 'form-select'; mode.dataset.soilMode = '';
    mode.add(new Option(t('Profondità da 0 (m)', 'Profondeurs depuis 0 (m)'), 'depth'));
    mode.add(new Option(t('Quote', 'Cotes'), 'elevation')); label.append(mode);
    const originText = document.createElement('p'); originText.dataset.soilOrigin = '';
    toolbar.append(label, originText); root.prepend(toolbar);
    const summary = document.createElement('div'); summary.dataset.soilCoordinateUi = '';
    summary.dataset.soilSummary = ''; summary.className = 'soil-coordinate-summary'; root.append(summary);
    const bound = new WeakSet();
    const pairs = () => [...root.querySelectorAll(options.row)].map(row => ({row,
      start: row.querySelector(options.start), end: row.querySelector(options.end)}));
    function refresh() {
      const origin = options.origin(), datum = options.datum() || 'NGF';
      mode.options[1].textContent = `${t('Quote', 'Cotes')} ${datum} (m)`;
      mode.options[1].disabled = origin === null;
      if (origin === null) mode.value = 'depth';
      originText.textContent = origin === null ? t('Indica la quota di partenza per vedere le quote.', 'Indiquez la cote de départ pour afficher les cotes.') :
        `${t('Zero scavo', 'Zéro de forage')} = ${format(origin)} ${datum}. ${t('La profondità aumenta scendendo.', 'La profondeur augmente en descendant.')}`;
      const elevations = mode.value === 'elevation';
      root.querySelectorAll('[data-soil-heading]').forEach((el, i) => el.textContent = elevations ?
        `${i ? t('Quota a', 'Cote à') : t('Quota da', 'Cote de')} (${datum})` : `${i ? t('A', 'À') : t('Da', 'De')} (m)`);
      const records = [];
      pairs().forEach(({row, start, end}) => {
        if (!start || !end) return;
        [start, end].forEach((input, i) => {
          if (!bound.has(input)) {
            // New fiche rows can be cloned from a row which already has proxies.
            if (input.nextElementSibling?.matches('[data-soil-elevation]')) input.nextElementSibling.remove();
            const proxy = document.createElement('input'); proxy.type = 'number'; proxy.step = '0.01';
            proxy.className = 'form-control'; proxy.dataset.soilElevation = i ? 'end' : 'start';
            input.after(proxy); input.soilProxy = proxy; bound.add(input);
            proxy.addEventListener('input', () => {
              const level = number(proxy.value), zero = options.origin();
              input.value = level === null || zero === null ? '' : String(Math.round((zero - level) * 1e6) / 1e6);
              input.dispatchEvent(new Event('input', {bubbles:true}));
            });
          }
          const proxy = input.soilProxy, depth = number(input.value);
          input.hidden = elevations; proxy.hidden = !elevations;
          proxy.disabled = !elevations;
          if (document.activeElement !== proxy) proxy.value = depth === null || origin === null ? '' : format(origin - depth);
          const title = elevations ? `${i ? t('Quota a', 'Cote à') : t('Quota da', 'Cote de')} (${datum})` : `${i ? t('A', 'À') : t('Da', 'De')} (m)`;
          proxy.setAttribute('aria-label', title);
          const fieldLabel = input.closest('.form-group')?.querySelector('label');
          if (fieldLabel) fieldLabel.textContent = title;
          proxy.setCustomValidity(depth !== null && depth < 0 ? t('La quota supera la partenza dello scavo.', 'La cote dépasse le départ du forage.') : '');
        });
        const from = number(start.value), to = number(end.value);
        if (from !== null && to !== null) records.push([options.material(row) || '—',
          `${format(from)} → ${format(to)} m`, origin === null ? '—' : `${format(origin-from)} → ${format(origin-to)} ${datum}`]);
      });
      summary.replaceChildren();
      if (records.length) {
        const table = document.createElement('table'); table.className = 'data-table';
        const head = table.createTHead().insertRow();
        [t('Terreno', 'Sol'), t('Profondità da partenza', 'Profondeur depuis le départ'), t('Quote', 'Cotes')].forEach(text => {
          const th = document.createElement('th'); th.textContent = text; head.append(th);
        });
        const body = table.createTBody(); records.forEach(record => {const row = body.insertRow(); record.forEach(text => row.insertCell().textContent = text);});
        summary.append(table);
      }
      options.onRefresh?.();
    }
    mode.addEventListener('change', refresh);
    root.addEventListener('input', refresh); root.addEventListener('change', refresh);
    const observer = new MutationObserver(refresh);
    observer.observe(options.rows, {childList:true});
    root.soilCoordinates = {refresh, mode}; refresh(); return root.soilCoordinates;
  }
  return {bind, number, format};
})();
