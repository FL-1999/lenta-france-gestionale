(() => {
  const form = document.getElementById('rapportino-form');
  if (!form) return;
  const status = document.getElementById('draft-status');
  const fr = document.documentElement.lang === 'fr';
  const tr = (it, french) => fr ? french : it;
  const keys = ['data', 'cantiere_id', 'ore_totali', 'total_personale', 'macchinari', 'attivita', 'note'];
  let revision = 0, ready = false, dirty = false, timer, pending, submitted = false, submission;
  const snapshot = () => ({fields: Object.fromEntries(keys.map(key => [key, document.getElementById(key).value])),
                           capo: readPreviousCapoRow(), workers: readPreviousRows()});
  async function request(method, body) {
    const response = await fetch('/operazioni/bozza', {method, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
    if (!response.ok) throw new Error(response.status === 409
      ? tr('Bozza modificata in un’altra scheda. Ricarica prima di continuare.', 'Brouillon modifié dans un autre onglet. Rechargez avant de continuer.')
      : tr('Bozza non salvata. Verifica connessione e sessione.', 'Brouillon non enregistré. Vérifiez la connexion et la session.'));
    return response.json();
  }
  async function save() {
    if (pending) { await pending; return save(); }
    if (!ready) throw new Error(status.textContent);
    if (!dirty) return;
    const payload = snapshot();
    dirty = false;
    status.textContent = tr('Salvataggio bozza…', 'Enregistrement du brouillon…');
    pending = request('PUT', {revision, payload});
    try {
      const result = await pending;
      revision = result.revision;
      status.textContent = tr('Bozza salvata alle ', 'Brouillon enregistré à ') + new Date(result.updated_at).toLocaleTimeString();
    } catch (error) {
      dirty = true;
      status.textContent = error.message;
      throw error;
    } finally { pending = null; }
    if (dirty) return save();
  }
  const initialization = (async () => {
    form.inert = true;
    try {
      const result = await request('GET');
      revision = result.revision;
      if (result.payload?.fields) {
        for (const key of keys) if (Object.hasOwn(result.payload.fields, key)) document.getElementById(key).value = result.payload.fields[key];
        workersContainer.replaceChildren(buildCapoRow(result.payload.capo || {}));
        const count = getTotalPersonnelValue() - 1;
        for (let i = 0; i < count; i++) workersContainer.appendChild(buildWorkerRow(result.payload.workers?.[i] || {}));
        validateIncompleteDays();
        status.textContent = tr('Bozza ripristinata. Controlla data, cantiere, persone e ore prima di inviare.', 'Brouillon restauré. Vérifiez date, chantier, personnes et heures avant envoi.');
      } else {
        const now = new Date();
        if (!document.getElementById('data').value) document.getElementById('data').value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
        status.textContent = tr('Le modifiche saranno salvate come bozza personale. Nessuna ora viene registrata prima dell’invio.', 'Les modifications seront enregistrées comme brouillon personnel. Aucune heure ne sera enregistrée avant envoi.');
      }
      ready = true;
    } catch (error) { status.textContent = error.message; }
    finally { form.inert = false; }
  })();
  function schedule() {
    if (submitted) return;
    dirty = true;
    clearTimeout(timer);
    timer = setTimeout(() => save().catch(() => {}), 700);
  }
  form.addEventListener('input', schedule);
  form.addEventListener('change', schedule);
  document.getElementById('copy-previous-report').addEventListener('click', async () => {
    const site = document.getElementById('cantiere_id').value;
    const day = document.getElementById('data').value;
    if (!site || !day) { status.textContent = tr('Scegli prima data e cantiere.', 'Choisissez une date et un chantier.'); return; }
    if (!confirm(tr('Sostituire attività, note e squadra con l’ultimo rapportino? Controlla i dati prima di inviare.', 'Remplacer activités, notes et équipe par le dernier rapport ? Vérifiez les données avant envoi.'))) return;
    try {
      const response = await fetch(`/operazioni/ultimo-rapportino?site_id=${encodeURIComponent(site)}&before=${encodeURIComponent(day)}`);
      if (!response.ok) throw new Error(tr('Nessun rapportino precedente disponibile.', 'Aucun rapport précédent disponible.'));
      const previous = await response.json();
      if (previous.workers.length > 10) throw new Error(tr('Squadra troppo numerosa per questa schermata.', 'Équipe trop nombreuse pour cet écran.'));
      Object.entries(previous.fields).forEach(([key, value]) => document.getElementById(key).value = value);
      const capo = previous.workers.find(worker => worker.personale_id === CAPOSQUADRA.id) || {};
      const others = previous.workers.filter(worker => worker.personale_id !== CAPOSQUADRA.id);
      workerCountInput.value = String(others.length + 1);
      workersContainer.replaceChildren(buildCapoRow(capo), ...others.map(buildWorkerRow));
      validateIncompleteDays();
      schedule();
      status.textContent = tr('Dati copiati: ricontrolla persone, ore e attività.', 'Données copiées : vérifiez personnes, heures et activités.');
    } catch (error) { status.textContent = error.message; }
  });
  window.addEventListener('online', () => { if (ready && dirty) save().catch(() => {}); });
  window.addEventListener('beforeunload', event => { if (!submitted && (dirty || pending)) { event.preventDefault(); event.returnValue = ''; } });
  window.reportDraft = {
    async prepareSubmit() {
      await initialization;
      clearTimeout(timer);
      const fingerprint = JSON.stringify(snapshot());
      if (submission?.fingerprint === fingerprint) return submission.revision;
      dirty = true;
      await save();
      submission = {revision, fingerprint};
      return revision;
    },
    rejected() { submission = null; },
    submitted() { submitted = true; dirty = false; clearTimeout(timer); }
  };
})();
