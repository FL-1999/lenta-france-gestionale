/* Per-tab presentation history. Never changes a business request or sends data. */
(() => {
  'use strict';
  const context = document.querySelector('[data-purchase-context]');
  if (!context) return;
  const account = `${context.dataset.user}:${context.dataset.role}`;
  const key = `lf-purchasing-navigation-v1:${account}`;
  const back = context.querySelector('[data-purchase-return]');
  const fallbackBack = {href: back.getAttribute('href'), text: back.textContent, hidden: back.hidden};
  const roots = [...document.querySelectorAll('[data-purchase-section]')];
  const lists = new Set(['/manager/ordini', '/manager/ordini/chiusi', '/manager/fornitori',
    '/manager/magazzino', '/manager/magazzino/items', '/manager/magazzino/movimenti',
    '/manager/magazzino/richieste', '/manager/magazzino/categorie', '/manager/magazzino/macros',
    '/manager/magazzino/archiviati', '/manager/magazzino/sotto-soglia']);
  const pages = /^\/manager\/(?:ordini(?:\/(?:nuovo|chiusi|email-wizard|\d+(?:\/(?:bolle\/nuova|fattura|email))?))?|fornitori(?:\/(?:nuovo|\d+))?|magazzino(?:\/(?:dashboard|items(?:\/\d+\/(?:scheda|duplica|rettifica))?|nuovo|\d+\/modifica|movimenti|report-consumi|richieste(?:\/\d+)?|categorie(?:\/(?:nuova|\d+\/(?:modifica|sposta)))?|macros|macro\/(?:nuova|\d+\/modifica)|archiviati|sotto-soglia))?)$/;
  function safe(value) {
    try {
      if (typeof value !== 'string' || value.length > 4000) return null;
      const url = new URL(value, location.origin);
      if (url.origin !== location.origin || url.username || url.password || !pages.test(url.pathname)) return null;
      return url;
    } catch (_) { return null; }
  }
  function read(name) { try { return JSON.parse(sessionStorage.getItem(key + name)); } catch (_) { return null; } }
  function write(name, value) { try { sessionStorage.setItem(key + name, JSON.stringify(value)); } catch (_) {} }
  function clear(name) { try { sessionStorage.removeItem(key + name); } catch (_) {} }
  function cleanTrail(value) {
    if (!Array.isArray(value)) return [];
    return value.slice(-15).filter(entry => entry && safe(entry.url) && typeof entry.title === 'string')
      .map(entry => ({url: safe(entry.url).pathname + safe(entry.url).search + safe(entry.url).hash,
                     title: entry.title.slice(0, 160), y: Number.isFinite(entry.y) ? Math.max(0, Math.min(entry.y, 1000000)) : 0}));
  }
  const currentURL = () => location.pathname + location.search + location.hash;
  const canonical = value => { const u = safe(value); return u ? u.pathname + u.search : null; };
  const headingText = () => (document.querySelector('main h1')?.textContent || document.title)
    .replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, '').replace(/\s+/g, ' ').trim();
  const title = () => {
    let value = headingText();
    if (context.dataset.list === 'true') {
      const q = new URL(location.href).searchParams.get('q');
      if (q) value += ' · ' + q.slice(0, 60);
    }
    return value.slice(0, 160);
  };
  let trail = [];
  const stored = history.state?.lfPurchasing;
  const pending = read(':pending');
  let restoreY = null;
  clear(':pending');
  if (stored?.account === account) {
    trail = cleanTrail(stored.trail);
  } else if (pending?.account === account && Date.now() - pending.time < 60000 &&
             (canonical(pending.target) === canonical(currentURL()) ||
              (pending.post && pending.section === context.dataset.section))) {
    trail = cleanTrail(pending.trail);
    restoreY = Number.isFinite(pending.restoreY) ? Math.max(0, Math.min(pending.restoreY, 1000000)) : null;
  }
  // A save often redirects back to the record that opened the form.
  while (trail.length && canonical(trail[trail.length - 1].url) === canonical(currentURL())) trail.pop();
  function rememberHistory() {
    try { history.replaceState({...history.state, lfPurchasing: {account, trail}}, '', location.href); } catch (_) {}
  }
  function refresh() {
    const crumb = context.querySelector('[data-purchase-page]');
    if (crumb) crumb.textContent = headingText();
    back.setAttribute('href', fallbackBack.href);
    back.textContent = fallbackBack.text;
    back.hidden = fallbackBack.hidden;
    if (trail.length) {
      back.href = trail[trail.length - 1].url;
      back.textContent = '← ' + context.dataset.backLabel + ' ' + trail[trail.length - 1].title;
      back.hidden = false;
    }
    const savedLists = read(':lists');
    const remembered = savedLists && typeof savedLists === 'object' && !Array.isArray(savedLists) ? savedLists : {};
    if (context.dataset.list === 'true' && lists.has(location.pathname)) {
      remembered[context.dataset.section] = currentURL();
      write(':lists', remembered);
    }
    roots.forEach(link => {
      const candidate = safe(remembered[link.dataset.purchaseSection]);
      // Only a list in the matching section can replace a section's default URL.
      const original = new URL(link.dataset.purchaseDefault || link.href, location.origin);
      link.dataset.purchaseDefault = original.pathname;
      link.href = original.pathname;
      const sameSection = candidate && (candidate.pathname === original.pathname ||
        (link.dataset.purchaseSection === 'orders' && candidate.pathname === '/manager/ordini/chiusi') ||
        (link.dataset.purchaseSection === 'items' && candidate.pathname === '/manager/magazzino/items'));
      if (sameSection && lists.has(candidate.pathname)) link.href = candidate.pathname + candidate.search;
    });
  }
  function pendingNavigation(target, nextTrail, post = false, restoreY = null) {
    write(':pending', {account, target, trail: cleanTrail(nextTrail), time: Date.now(), post,
                       section: context.dataset.section, restoreY});
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey ||
        event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
    const url = safe(link.href);
    if (!url || canonical(url.href) === canonical(currentURL())) return;
    if (link.hasAttribute('data-purchase-return')) {
      pendingNavigation(url.href, trail.slice(0, -1), false, trail[trail.length - 1]?.y);
    } else if (link.hasAttribute('data-purchase-section') || link.hasAttribute('data-purchase-root')) {
      pendingNavigation(url.href, []);
    } else {
      // Cancel links and links to an ancestor should not create a return loop.
      const ancestor = trail.map(entry => canonical(entry.url)).lastIndexOf(canonical(url.href));
      if (ancestor >= 0) {
        pendingNavigation(url.href, trail.slice(0, ancestor), false, trail[ancestor].y);
        return;
      }
      // State tabs, pagination and category drill-down have their own local navigation.
      const sameList = lists.has(location.pathname) && lists.has(url.pathname) &&
        (location.pathname === url.pathname || context.dataset.section === 'orders' && url.pathname.startsWith('/manager/ordini'));
      pendingNavigation(url.href, sameList ? trail : [...trail, {url:currentURL(), title:title(), y:window.scrollY}]);
    }
  });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented || form.target) return;
    const method = (form.method || 'get').toLowerCase();
    if (method === 'get') {
      const url = safe(form.action || location.href);
      if (!url) return;
      url.search = new URLSearchParams(new FormData(form)).toString();
      pendingNavigation(url.href, trail);
    } else {
      // Carry the current parent across the normal server POST/redirect, without touching the form.
      pendingNavigation(currentURL(), trail, true);
    }
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    trail = history.state?.lfPurchasing?.account === account ? cleanTrail(history.state.lfPurchasing.trail) : [];
    clear(':pending'); refresh();
  });
  rememberHistory(); refresh();
  if (restoreY !== null) requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo(0, restoreY)));
})();
