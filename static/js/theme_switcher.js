(() => {
  const root = document.documentElement;
  let stored;
  try { stored = localStorage.getItem('appTheme'); } catch (_) { /* Storage can be disabled. */ }
  const preferred = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  function apply(theme) {
    root.setAttribute('data-theme', theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#102237' : '#edede8');
    document.getElementById('theme-toggle')?.setAttribute('aria-pressed', String(theme === 'dark'));
  }
  apply(['light', 'dark'].includes(stored) ? stored : preferred);
  document.addEventListener('DOMContentLoaded', () => {
    apply(root.getAttribute('data-theme'));
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      apply(next);
      try { localStorage.setItem('appTheme', next); } catch (_) { /* Keep working without persistence. */ }
    });
  });
})();
