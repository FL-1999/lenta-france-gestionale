(() => {
  const roots = document.querySelectorAll('.pw-admin-controls');
  const fr = document.documentElement.lang === 'fr';
  const t = (it, french) => fr ? french : it;
  let unsavedDetails = false;
  document.getElementById('personnel-details-form')?.addEventListener('input', () => { unsavedDetails = true; });
  roots.forEach(root => root.addEventListener('submit', async event => {
    const form = event.target.closest('[data-admin-action]');
    if (!form) return;
    event.preventDefault();
    const feedback = root.querySelector('.pw-admin-feedback');
    const button = form.querySelector('[type=submit]');
    feedback.hidden = true;
    button.disabled = true;
    try {
      if (unsavedDetails) throw new Error(t('Salva prima le modifiche ai dati anagrafici in alto.', 'Enregistrez d’abord les modifications de la fiche ci-dessus.'));
      const values = Object.fromEntries(new FormData(form));
      let path, body;
      if (form.dataset.adminAction === 'create') {
        if (values.password !== values.password_confirm) throw new Error(t('Le password non coincidono.', 'Les mots de passe ne correspondent pas.'));
        path = `/manager/personale/${root.dataset.personId}/crea-accesso`;
        body = {email: values.email, password: values.password, role: values.role, language: values.language};
      } else if (form.dataset.adminAction === 'link') {
        path = `/manager/personale/${root.dataset.personId}/account`;
        body = {user_id: Number(values.user_id)};
      } else if (form.dataset.adminAction === 'role') {
        path = `/manager/personale/${root.dataset.personId}/tipo-accesso`;
        body = {user_id: Number(form.dataset.userId), expected: form.dataset.expected, role: values.role};
      } else {
        path = '/manager/personale/presenze/elenco';
        body = {people: [...form.querySelectorAll('[data-attendance-person]')].filter(input => input.checked !== (input.dataset.expected === 'true')).map(input => ({person_id: Number(input.dataset.attendancePerson), included: input.checked, expected: input.dataset.expected === 'true'}))};
        if (!body.people.length) { button.disabled = false; return; }
      }
      const response = await fetch(path, {method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf}, body:JSON.stringify(body)});
      if (response.redirected) throw new Error(t('Sessione scaduta: accedi nuovamente.', 'Session expirée : reconnectez-vous.'));
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : t('Controlla i dati inseriti.', 'Vérifiez les données saisies.'));
      form.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; });
      location.reload();
    } catch (error) {
      feedback.textContent = error.message;
      feedback.hidden = false;
      feedback.scrollIntoView({block:'center',behavior:'smooth'});
      button.disabled = false;
    }
  }));
  // Keep the optional historical view while navigating weeks and months.
  if (new URLSearchParams(location.search).get('show_excluded') === 'true' && roots.length) {
    document.querySelectorAll('a[href]').forEach(link => {
      const url = new URL(link.href);
      if (url.origin === location.origin && url.pathname === '/manager/personale/presenze' && !url.searchParams.has('show_excluded')) {
        url.searchParams.set('show_excluded','true'); link.href = url.href;
      }
    });
    document.querySelectorAll('form[method=get]').forEach(form => {
      if (!form.querySelector('[name=show_excluded]')) { const input = document.createElement('input'); input.type='hidden'; input.name='show_excluded'; input.value='true'; form.append(input); }
    });
  }
})();
