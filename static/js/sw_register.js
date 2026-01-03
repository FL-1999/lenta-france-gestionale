if ('serviceWorker' in navigator && window.location.protocol === 'https:') {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js').catch((error) => {
      console.warn('Service worker registration failed:', error);
    });
  });
}
