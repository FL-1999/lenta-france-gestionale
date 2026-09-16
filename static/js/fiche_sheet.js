/* Fit the complete technical drawing to its container, not the browser width.
   Print styles reset the transform so PDF and paper retain their A4 geometry. */
(() => {
  'use strict';
  const viewport = document.querySelector('[data-sheet-viewport]');
  const sheet = document.getElementById('technical-sheet-export');
  if (!viewport || !sheet) return;
  const designWidth = 1080;
  function fit() {
    if (window.matchMedia('print').matches) return;
    sheet.style.width = `${designWidth}px`;
    const scale = Math.min(1, viewport.clientWidth / designWidth);
    sheet.style.transform = `scale(${scale})`;
    viewport.style.height = `${Math.ceil(sheet.offsetHeight * scale)}px`;
  }
  new ResizeObserver(fit).observe(viewport);
  new ResizeObserver(fit).observe(sheet);
  sheet.querySelectorAll('img').forEach(img => img.addEventListener('load', fit));
  window.addEventListener('afterprint', fit);
  document.fonts?.ready.then(fit);
  fit();
})();
