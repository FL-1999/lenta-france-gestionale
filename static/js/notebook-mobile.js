/* Presentation only: keep the existing form, permissions and save handlers. */
(() => {
  'use strict';
  const root = document.getElementById('notebook');
  const frame = root?.closest('.workspace-frame');
  if (!root || !['admin', 'manager'].includes(frame?.dataset.role)) return;
  const phone = matchMedia('(max-width:767px)');
  frame.classList.add('notebook-management');
  let pending = false;

  function fit(field) {
    // Activity titles retain the original single-line input semantics.
    // The textarea adds visual wrapping without introducing hidden line breaks on PC.
    const value = field.value.replace(/[\r\n]+/g, ' ');
    if (field.value !== value) {
      const caret = field.selectionStart;
      const prefix = field.value.slice(0, caret).replace(/[\r\n]+/g, ' ');
      field.value = value;
      field.setSelectionRange(prefix.length, prefix.length);
    }
    field.style.height = '0px';
    field.style.height = Math.max(70, Math.min(300, field.scrollHeight + 2)) + 'px';
  }
  function refresh() {
    pending = false;
    root.classList.toggle('nb-management-phone', phone.matches);
    root.dataset.noteKind = root.querySelector('[name=kind]')?.value || '';
    root.querySelectorAll('[data-action-text]').forEach(current => {
      let field = current;
      const tag = phone.matches ? 'TEXTAREA' : 'INPUT';
      if (field.tagName !== tag) {
        const focused = document.activeElement === field;
        const start = field.selectionStart, end = field.selectionEnd;
        const replacement = document.createElement(tag.toLowerCase());
        for (const attr of field.attributes) {
          if (!['type', 'rows', 'style', 'value'].includes(attr.name)) {
            replacement.setAttribute(attr.name, attr.value);
          }
        }
        replacement.value = field.value;
        if (phone.matches) replacement.rows = 2;
        field.replaceWith(replacement);
        field = replacement;
        if (focused) {
          field.focus({preventScroll:true});
          field.setSelectionRange(start, end);
        }
      }
      if (phone.matches) fit(field);
    });
  }
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(refresh);
  }
  root.addEventListener('input', event => {
    if (phone.matches && event.target.matches('textarea[data-action-text]')) fit(event.target);
  });
  root.addEventListener('keydown', event => {
    if (phone.matches && event.key === 'Enter' && !event.isComposing &&
        event.target.matches('textarea[data-action-text]')) event.preventDefault();
  });
  root.addEventListener('change', event => {
    if (event.target.matches('[name=kind]')) schedule();
  });
  new MutationObserver(schedule).observe(root, {childList:true, subtree:true});
  phone.addEventListener('change', schedule);
  window.addEventListener('resize', schedule);
  refresh();
})();
