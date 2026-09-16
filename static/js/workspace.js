/* Shared navigation. No business actions or network requests are performed here. */
(() => {
  'use strict';
  const sidebar = document.getElementById('workspace-sidebar');
  const toggles = [...document.querySelectorAll('[data-workspace-toggle]')];
  const scrim = document.querySelector('.workspace-scrim');
  const frame = document.querySelector('.workspace-frame');
  const bottom = document.querySelector('.workspace-bottom-nav');
  const mobile = window.matchMedia('(max-width: 1023px)');
  let opener = null;
  function setDrawer(requested, restore = true) {
    if (!sidebar) return;
    const open = requested && mobile.matches;
    sidebar.classList.toggle('is-open', open);
    document.body.classList.toggle('workspace-menu-open', open);
    sidebar.inert = mobile.matches && !open;
    sidebar.setAttribute('aria-hidden', String(sidebar.inert));
    if (open) { sidebar.setAttribute('role', 'dialog'); sidebar.setAttribute('aria-modal', 'true'); }
    else { sidebar.removeAttribute('role'); sidebar.removeAttribute('aria-modal'); }
    toggles.forEach(button => button.setAttribute('aria-expanded', String(open)));
    if (scrim) scrim.hidden = !open;
    if (frame) frame.inert = open;
    if (bottom) bottom.inert = open;
    if (open) requestAnimationFrame(() => {
      if (sidebar.classList.contains('is-open')) sidebar.querySelector('[data-workspace-close]').focus();
    });
    else if (restore && opener) { opener.focus(); opener = null; }
  }
  toggles.forEach(button => button.addEventListener('click', () => {
    opener = button;
    setDrawer(!sidebar.classList.contains('is-open'));
  }));
  document.querySelectorAll('[data-workspace-close]').forEach(button => button.addEventListener('click', () => setDrawer(false)));
  sidebar?.addEventListener('click', event => { if (event.target.closest('a[href]')) setDrawer(false, false); });
  document.addEventListener('keydown', event => {
    if (!sidebar?.classList.contains('is-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); setDrawer(false); }
    if (event.key === 'Tab') {
      const focusable = [...sidebar.querySelectorAll('a[href],button,summary')].filter(el => el.getClientRects().length && !el.disabled);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  mobile.addEventListener('change', () => setDrawer(false));
  setDrawer(false, false);
  const heading = document.querySelector('main h1');
  const breadcrumb = document.querySelector('.workspace-current-page');
  if (heading && breadcrumb) breadcrumb.textContent = heading.textContent.trim();

  const dropdowns = [...document.querySelectorAll('[data-nav-dropdown]')];
  function closeDropdown(dropdown) {
    dropdown.classList.remove('is-open');
    dropdown.querySelector('[data-nav-dropdown-toggle]')?.setAttribute('aria-expanded', 'false');
  }
  dropdowns.forEach(dropdown => {
    const toggle = dropdown.querySelector('[data-nav-dropdown-toggle]');
    toggle?.addEventListener('click', event => {
      event.stopPropagation();
      const open = !dropdown.classList.contains('is-open');
      dropdowns.forEach(closeDropdown);
      dropdown.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
    });
    dropdown.querySelector('[data-nav-dropdown-menu]')?.addEventListener('click', event => event.stopPropagation());
  });
  document.addEventListener('click', () => dropdowns.forEach(closeDropdown));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    dropdowns.filter(dropdown => dropdown.classList.contains('is-open')).forEach(dropdown => {
      closeDropdown(dropdown);
      dropdown.querySelector('[data-nav-dropdown-toggle]')?.focus();
    });
  });
  document.querySelectorAll('main table.data-table, main table.table').forEach(table => {
    if (table.closest('.table-responsive,.table-wrapper,.workspace-table-scroll,.fiche-sheet,.fiche-paper')) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'workspace-table-scroll';
    table.before(wrapper);
    wrapper.append(table);
  });
})();
