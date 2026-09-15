(() => {
  const fr = document.documentElement.lang === 'fr';
  const fallback = fr ? 'Enregistrement impossible. Vérifiez les données et réessayez.' : 'Salvataggio non riuscito. Controlla i dati e riprova.';
  async function send(form, url, options) {
    const error = form.querySelector('[data-ops-error]');
    const buttons = [...form.querySelectorAll('button')];
    buttons.forEach(button => button.disabled = true);
    error.textContent = '';
    try {
      const response = await fetch(url, {...options, credentials: 'same-origin'});
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : fallback);
      }
      if (response.redirected) window.location.assign(response.url);
      else window.location.reload();
    } catch (e) {
      error.textContent = e.message || fallback;
      buttons.forEach(button => button.disabled = false);
    }
  }
  document.querySelectorAll('[data-ops-form]').forEach(form => {
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;
      const data = new FormData(form);
      if (event.submitter?.name) data.set(event.submitter.name, event.submitter.value);
      send(form, form.action, {method: 'POST', body: data});
    });
  });
  document.querySelectorAll('[data-report-edit]').forEach(form => {
    form.addEventListener('submit', event => {
      event.preventDefault();
      const payload = JSON.parse(form.dataset.reportPayload);
      ['activities', 'machines_used', 'notes'].forEach(key => payload[key] = form.elements[key].value);
      payload.total_hours = Number(form.elements.total_hours.value);
      payload.workers.forEach(worker => worker.hours_worked = Number(form.querySelector(`[data-worker-id="${worker.personale_id}"]`).value));
      send(form, `/reports/${form.dataset.reportEdit}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    });
  });
})();
