/* Phone-only presentation of explicitly selected, read-only directories.
 * Original rows and controls remain authoritative (filters, permissions, forms).
 * Editable tables must not opt in to this component.
 */
(() => {
  'use strict';
  if (!window.HTMLDialogElement || !HTMLDialogElement.prototype.showModal) return;
  const phone = matchMedia('(max-width: 767px)');
  const fr = document.documentElement.lang.startsWith('fr');
  const words = fr
    ? {details: 'Détails et actions', close: 'Fermer', actions: 'Actions', info: 'Informations', map: 'Carte'}
    : {details: 'Dettagli e azioni', close: 'Chiudi', actions: 'Azioni', info: 'Informazioni', map: 'Mappa'};
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const text = node => {
    if (!node) return '';
    const copy = node.cloneNode(true);
    copy.querySelectorAll('script,style,button,input,select,textarea,svg').forEach(n => n.remove());
    copy.querySelectorAll('[data-mobile-text]').forEach(n => n.replaceWith(n.dataset.mobileText));
    copy.querySelectorAll('br').forEach(n => n.replaceWith(' · '));
    return (node.dataset.mobileText || copy.textContent).replace(/\s+/g, ' ').trim();
  };
  const useful = value => value && !['-', '—', '–'].includes(value);
  const indices = value => (value || '').split(',').filter(v => v.trim() !== '').map(Number);
  let dialog, dialogTitle, dialogBody, opener;
  function makeDialog() {
    dialog = el('dialog', 'mobile-directory-dialog');
    dialog.setAttribute('aria-labelledby', 'mobile-directory-title');
    const header = el('div', 'mobile-directory-dialog__header');
    dialogTitle = el('h2', '', ''); dialogTitle.id = 'mobile-directory-title';
    const close = el('button', 'mobile-directory-close', '×');
    close.type = 'button'; close.setAttribute('aria-label', words.close);
    close.addEventListener('click', () => dialog.close());
    dialogBody = el('div', 'mobile-directory-dialog__body');
    header.append(dialogTitle, close); dialog.append(header, dialogBody);
    document.body.append(dialog);
    dialog.addEventListener('close', () => {
      document.documentElement.classList.remove('mobile-directory-dialog-open');
      if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus({preventScroll: true}); }
    });
    dialog.addEventListener('click', event => { if (event.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
    }});
    phone.addEventListener('change', () => { if (!phone.matches && dialog.open) dialog.close(); });
  }
  function openDetails(record, trigger) {
    if (!phone.matches) return;
    if (!dialog) makeDialog();
    opener = trigger; dialogTitle.textContent = record.title;
    dialogBody.replaceChildren();
    const facts = el('dl', 'mobile-directory-facts');
    record.fields.forEach(field => {
      const pair = el('div');
      pair.append(el('dt', '', field.label), el('dd', '', field.value || '—'));
      facts.append(pair);
    });
    dialogBody.append(facts);
    if (record.controls.length) {
      dialogBody.append(el('h3', '', words.actions));
      const actions = el('div', 'mobile-directory-actions');
      record.controls.forEach(source => {
        const label = source.getAttribute('aria-label') || source.getAttribute('title') || source.textContent.trim();
        const action = el(source.matches('a[href]') ? 'a' : 'button', 'mobile-directory-action',
          source.matches('.btn-site-map') ? words.map : label.replace(/\s+/g, ' '));
        if (action.tagName === 'A') {
          ['href', 'target', 'rel', 'download'].forEach(attr => {
            if (source.hasAttribute(attr)) action.setAttribute(attr, source.getAttribute(attr));
          });
        } else { action.type = 'button'; action.disabled = source.disabled; }
        if (source.matches('.btn-danger,.btn-outline-danger') || source.closest('form[action$="/delete"]')) action.classList.add('is-danger');
        action.addEventListener('click', event => {
          if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          opener.setAttribute('aria-expanded', 'false'); opener = null;
          dialog.close();
          // Delegate to the existing control, preserving handlers, CSRF and confirmations.
          source.click();
        });
        actions.append(action);
      });
      dialogBody.append(actions);
    }
    trigger.setAttribute('aria-expanded', 'true');
    dialog.showModal(); document.documentElement.classList.add('mobile-directory-dialog-open');
  }
  function rowView(record) {
    const row = el('li', 'mobile-directory-row');
    const content = el('div', 'mobile-directory-row__content');
    const title = el(record.primary ? 'a' : 'button', 'mobile-directory-name', record.title);
    if (record.primary) {
      ['href', 'target', 'rel', 'download'].forEach(attr => {
        if (record.primary.hasAttribute(attr)) title.setAttribute(attr, record.primary.getAttribute(attr));
      });
    }
    else { title.type = 'button'; title.addEventListener('click', () => openDetails(record, more)); }
    content.append(title);
    if (record.meta.length) {
      const meta = el('div', 'mobile-directory-meta');
      record.meta.filter(useful).forEach(value => meta.append(el('span', '', value)));
      content.append(meta);
    }
    if (record.status.length) {
      const statuses = el('div', 'mobile-directory-statuses');
      record.status.forEach(status => {
        if (useful(status.value)) statuses.append(el('span', `mobile-directory-status ${status.tone || ''}`, status.value));
      });
      content.append(statuses);
    }
    const more = el('button', 'mobile-directory-more', '⋯'); more.type = 'button';
    more.setAttribute('aria-label', `${words.details}: ${record.title}`);
    more.setAttribute('aria-haspopup', 'dialog'); more.setAttribute('aria-expanded', 'false');
    more.addEventListener('click', () => openDetails(record, more));
    row.append(content, more);
    const sync = () => { row.hidden = record.source.hidden || record.source.style.display === 'none'; };
    sync();
    new MutationObserver(sync).observe(record.source, {attributes: true, attributeFilter: ['style', 'hidden']});
    return row;
  }
  function tone(node) {
    if (node.matches('.badge-danger') || node.querySelector('.badge-danger')) return 'is-danger';
    if (node.matches('.badge-warning,.project-status--warning') || node.querySelector('.badge-warning,.project-status--warning')) return 'is-warning';
    if (node.matches('.badge-success,.project-status--ok') || node.querySelector('.badge-success,.project-status--ok')) return 'is-success';
    return '';
  }
  document.querySelectorAll('[data-mobile-toolbar]').forEach(source => {
    const primary = source.querySelector('a.btn-primary');
    if (!primary) return;
    const toolbar = el('div', 'mobile-directory-toolbar');
    const link = el('a', 'btn btn-primary', primary.textContent.replace(/\s+/g, ' ').trim());
    link.href = primary.href;
    const more = el('button', 'mobile-toolbar-more', '⋯'); more.type = 'button';
    more.setAttribute('aria-label', words.actions); more.setAttribute('aria-haspopup', 'dialog');
    more.setAttribute('aria-expanded', 'false');
    const record = {title: words.actions, fields: [], controls: [...source.querySelectorAll('a[href],button')].filter(n => n !== primary)};
    more.addEventListener('click', () => openDetails(record, more));
    toolbar.append(link, more); source.before(toolbar); source.classList.add('mobile-directory-source');
  });
  document.querySelectorAll('table[data-mobile-directory]').forEach(table => {
    const titleIndex = Number(table.dataset.mobileTitle || 0);
    const meta = indices(table.dataset.mobileMeta), statuses = indices(table.dataset.mobileStatus);
    const actionCols = indices(table.dataset.mobileActions), labeled = indices(table.dataset.mobileLabeledMeta);
    const headers = [...table.querySelectorAll('thead th')].map(text);
    const list = el('ul', 'mobile-directory');
    [...table.tBodies, ...(table.tFoot ? [table.tFoot] : [])].flatMap(body => [...body.rows]).forEach(source => {
      const cells = [...source.cells];
      if (cells.length === 1 && cells[0].colSpan > 1) {
        list.append(el('li', 'mobile-directory-empty', text(cells[0]))); return;
      }
      const titleCell = cells[titleIndex];
      if (!titleCell) return;
      const titleNode = table.dataset.mobileTitleSelector ? titleCell.querySelector(table.dataset.mobileTitleSelector) : titleCell;
      const record = {
        source, title: text(titleNode) || text(titleCell),
        primary: table.dataset.mobilePrimary ? source.querySelector(table.dataset.mobilePrimary) : null,
        meta: meta.map(i => useful(text(cells[i])) ? `${labeled.includes(i) ? headers[i] + ': ' : ''}${text(cells[i])}` : ''),
        status: statuses.filter(i => cells[i]).map(i => ({value: text(cells[i]), tone: tone(cells[i])})),
        fields: cells.flatMap((cell, i) => actionCols.includes(i) ? [] : [{label: headers[i] || words.info, value: text(cell)}]),
        controls: actionCols.flatMap(i => cells[i] ? [...cells[i].querySelectorAll('a[href],button:not([type=reset])')] : [])
      };
      list.append(rowView(record));
    });
    if (!list.children.length) return;
    let wrapper = table;
    while (wrapper.parentElement.matches('.workspace-table-scroll,.table-wrapper,.table-responsive,.table-container') && wrapper.parentElement.children.length === 1) wrapper = wrapper.parentElement;
    wrapper.before(list); wrapper.classList.add('mobile-directory-source');
    const body = list.closest('.card-body');
    if (body) body.classList.add('mobile-directory-host');
    const card = list.closest('.card');
    if (card) card.classList.add('mobile-directory-card');
    if (table.hasAttribute('data-mobile-hide-header') && card) card.classList.add('mobile-directory-card--no-heading');
    if (table.dataset.mobileLegacy) document.querySelectorAll(table.dataset.mobileLegacy).forEach(n => n.classList.add('mobile-directory-source'));
  });
  document.querySelectorAll('[data-mobile-cards]').forEach(sourceList => {
    const list = el('ul', 'mobile-directory');
    sourceList.querySelectorAll('[data-mobile-card]').forEach(source => {
      const title = source.querySelector('[data-mobile-name]');
      const record = {
        source, title: text(title), primary: title.querySelector('a[href]'),
        meta: [...source.querySelectorAll('[data-mobile-meta]')].map(text),
        status: [...source.querySelectorAll('[data-mobile-status]')].map(n => ({value: text(n), tone: tone(n)})),
        fields: [...source.querySelectorAll('[data-mobile-field]')].map(n => ({
          label: n.dataset.mobileField || words.info,
          value: n.matches('.value') ? n.textContent.trim() : text(n.querySelector('.value') || n)
        })),
        controls: [...source.querySelectorAll('.depot-actions a[href], [data-mobile-actions] a[href], [data-mobile-actions] button')]
      };
      list.append(rowView(record));
    });
    if (list.children.length) { sourceList.before(list); sourceList.classList.add('mobile-directory-source'); }
  });
})();
