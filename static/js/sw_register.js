// Registra il service worker per abilitare PWA (installabile + offline base).
// La navigazione usa strategia network-first (vedi sw.js): l'HTML è sempre
// fresco quando c'è rete, la pagina /offline è il fallback senza rete.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker
      .register('/static/sw.js?v=20260729')
      .catch(function (error) {
        console.warn('Service worker registration failed:', error);
      });
  });
}
