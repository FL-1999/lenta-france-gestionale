document.querySelectorAll('[data-fiche-translation]').forEach(button => {
  button.addEventListener('click', async () => {
    const box = button.closest('[data-translation-box]');
    const status = box.querySelector('[role=status]');
    const fr = document.documentElement.lang === 'fr';
    button.disabled = true;
    status.textContent = fr ? 'Traduction en cours…' : 'Traduzione in corso…';
    try {
      const response = await fetch(button.dataset.url, {method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams({csrf:button.dataset.token, source_hash:button.dataset.hash, report_lang:button.dataset.language})});
      if (!response.ok) { const data=await response.json(); throw new Error(typeof data.detail === 'string' ? data.detail : 'Ricarica / Rechargez'); }
      location.reload();
    } catch(error) { status.textContent=error.message; button.disabled=false; }
  });
});
