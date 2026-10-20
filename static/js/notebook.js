(() => {
  'use strict';
  const root = document.getElementById('notebook');
  if (!root) return;
  const fr = document.documentElement.lang === 'fr';
  const t = (it, french) => fr ? french : it;
  const q = selector => root.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const types = {free:t('Appunto libero','Note libre'),meeting:t('Riunione','Réunion'),list:t('Lista','Liste')};
  const state = {scope:root.dataset.site ? 'all' : 'mine', site:root.dataset.site, collection:'', query:'', offset:0,
    sites:[], collections:[], notes:[], current:null, dirty:false, busy:false, draft:null, more:false, ai_enabled:false};
  const dialog = q('#nb-dialog');
  let listGeneration = 0, detailGeneration = 0, newKey = null, aiKey = null, revisionOffset = 0;
  const date = value => new Date(value.endsWith('Z') ? value : value+'Z').toLocaleString(fr?'fr-FR':'it-IT',{dateStyle:'short',timeStyle:'short'});
  const button = (label, attr, primary=false) => `<button type="button" class="nb-button${primary?' nb-primary':''}" ${attr}>${label}</button>`;
  const option = (value, label, selected) => `<option value="${esc(value)}"${String(value)===String(selected)?' selected':''}>${esc(label)}</option>`;
  function error(err) { q('#nb-error').textContent=err.message; q('#nb-error').hidden=false; }
  function status(text) { q('#nb-status').textContent=text; q('#nb-status').hidden=!text; }
  async function api(path, method='GET', body) {
    const res = await fetch('/appunti'+path,{method,credentials:'same-origin',cache:'no-store',
      headers:{'Accept':'application/json',...(body ? {'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf} : {})},
      ...(body ? {body:JSON.stringify(body)} : {})});
    const data = await res.json().catch(()=>null);
    if (!res.ok || !data) throw new Error(typeof data?.detail==='string' ? data.detail :
      t('Impossibile completare l’operazione. Ricarica e verifica i dati.','Impossible de terminer. Rechargez et vérifiez les données.'));
    return data;
  }
  function leave() {
    return !state.dirty || confirm(t('Ci sono modifiche non salvate. Vuoi lasciarle?','Des modifications ne sont pas enregistrées. Les abandonner ?'));
  }
  function visibility(n) { return !n.shared ? t('Solo io','Moi uniquement') : n.owner ? t('Condiviso','Partagée') : t('Condiviso con te','Partagée avec vous'); }
  function setNoteUrl(id) {
    const url = new URL(location.href);
    if (id) url.searchParams.set('note',id); else url.searchParams.delete('note');
    history.replaceState(null,'',url);
  }
  function renderList() {
    q('#nb-list').innerHTML=state.notes.map(n=>`<button type="button" class="nb-row" data-note="${n.id}" aria-pressed="${state.current?.id===n.id}"><strong>${esc(n.title)}</strong><small>${types[n.kind]} · ${esc(date(n.updated_at))}</small>${n.site?`<small>${esc(n.site)}</small>`:''}<span class="nb-visibility">${visibility(n)}</span>${!n.owner?`<small>${esc(n.author)}</small>`:''}</button>`).join('') || `<p class="nb-muted">${t('Nessun appunto in questa vista.','Aucune note dans cette vue.')}</p>`;
    q('#nb-prev').hidden=!state.offset;q('#nb-next').hidden=!state.more;
    q('#nb-site-filter').innerHTML=option('',t('Tutti','Tous'),state.site)+state.sites.map(s=>option(s.id,s.name,state.site)).join('');
    q('#nb-collection-filter').innerHTML=option('',t('Tutte','Toutes'),state.collection)+state.collections.map(s=>option(s,s,state.collection)).join('');
    root.querySelectorAll('[data-scope]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scope===state.scope)));
  }
  async function loadList() {
    const generation=++listGeneration;
    const params=new URLSearchParams({scope:state.scope,q:state.query,collection:state.collection,offset:state.offset});
    if(state.site)params.set('site_id',state.site);
    const data=await api('/data?'+params);
    if(generation!==listGeneration)return;
    Object.assign(state,data);renderList();
  }
  function readContent(content) {
    const d=content.details||{};
    const list=(label,items)=>items?.length?`<section class="nb-section"><h3>${label}</h3><ul class="nb-readlist">${items.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></section>`:'';
    return `${content.body?`<p class="nb-readtext">${esc(content.body)}</p>`:''}
      ${d.when?`<p>${t('Data','Date')}: ${esc(d.when)}</p>`:''}
      ${list(t('Partecipanti','Participants'),d.attendees)}${list(t('Punti discussi','Points abordés'),d.agenda)}
      ${list(t('Decisioni','Décisions'),d.decisions)}
      ${d.actions?.length?`<section class="nb-section"><h3>${t('Attività / elenco','Actions / liste')}</h3><ul class="nb-readlist">${d.actions.map(a=>`<li>${a.done?'✓ ':''}${esc(a.text)}${a.assignee||a.due?`<p class="nb-help">${esc(a.assignee)}${a.assignee&&a.due?' · ':''}${esc(a.due)}</p>`:''}</li>`).join('')}</ul></section>`:''}`;
  }
  function actionRow(a) {
    return `<div class="nb-action-row"><div class="nb-action-main"><input type="checkbox" data-action-done aria-label="${t('Completata','Terminée')}" ${a.done?'checked':''}><input data-action-text aria-label="${t('Attività','Action')}" maxlength="1000" value="${esc(a.text)}">${button('×','data-remove-action aria-label="'+t('Rimuovi voce','Supprimer cet élément')+'"')}</div><div class="nb-action-meta"><label>${t('Responsabile (facoltativo)','Responsable (facultatif)')}<input data-action-assignee maxlength="150" value="${esc(a.assignee)}"></label><label>${t('Scadenza (facoltativa)','Échéance (facultative)')}<input data-action-due maxlength="100" value="${esc(a.due)}"></label></div></div>`;
  }
  function draftHtml() {
    const draft=state.draft;
    return draft?`<section class="nb-draft" aria-label="${t('Proposta da ricontrollare','Proposition à vérifier')}"><h2>${t('Proposta da ricontrollare','Proposition à vérifier')}</h2><p class="nb-help">${t('Non ancora applicata. Controlla nomi, numeri e decisioni.','Pas encore appliquée. Vérifiez les noms, chiffres et décisions.')}</p><h3>${esc(draft.result.title)}</h3>${readContent(draft.result)}${draft.result.warnings?.length?`<h3>${t('Da verificare','À vérifier')}</h3><ul>${draft.result.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}<div class="nb-actions">${button(t('Accetta bozza privata','Accepter le brouillon privé'),'data-draft-decision="accetta"',true)}${button(t('Scarta proposta','Ignorer la proposition'),'data-draft-decision="scarta"')}</div></section>`:'';
  }
  function renderEditor() {
    const n=state.current, editor=q('#nb-editor');
    state.dirty=false;
    if(!n){editor.innerHTML=`<p class="nb-muted">${t('Scegli un appunto oppure creane uno nuovo.','Choisissez une note ou créez-en une.')}</p>`;return;}
    const d=n.details||{}, canEdit=n.can_edit&&!n.archived;
    editor.innerHTML=button(t('← Torna all’elenco','← Retour à la liste'),'data-back')+
      `<div class="nb-topline"><span>${types[n.kind]}${n.archived?' · '+t('Archiviato','Archivée'):''}</span><span class="nb-visibility">${visibility(n)}</span></div>`+
      (canEdit?`<form id="nb-edit-form"><label>${t('Titolo','Titre')}<input name="title" class="nb-title-input" value="${esc(n.title)}" required maxlength="200"></label>
      <div class="nb-fields"><label>${t('Tipo','Type')}<select name="kind">${Object.entries(types).map(([v,label])=>option(v,label,n.kind)).join('')}</select></label>
      <label>${t('Cantiere collegato','Chantier associé')}<select name="site_id" ${!n.owner?'disabled':''}>${option('',t('Nessun cantiere','Aucun chantier'),n.site_id||'')}${state.sites.map(s=>option(s.id,s.name,n.site_id)).join('')}</select></label>
      ${n.owner?`<label class="nb-full">${t('Raccolta personale (facoltativa)','Collection personnelle (facultative)')}<input name="collection" list="nb-collections" value="${esc(n.collection)}" maxlength="100"><datalist id="nb-collections">${state.collections.map(s=>option(s,s,'')).join('')}</datalist></label>`:''}</div>
      <label>${t('Appunti','Notes')}<textarea name="body" class="nb-body" maxlength="30000" placeholder="${t('Scrivi qui, anche di fretta…','Écrivez ici, même rapidement…')}">${esc(n.body)}</textarea></label>
      <div data-meeting-fields ${n.kind==='meeting'?'':'hidden'}><div class="nb-fields"><label>${t('Data e ora','Date et heure')}<input name="when" maxlength="100" value="${esc(d.when)}"></label><label>${t('Partecipanti · uno per riga','Participants · un par ligne')}<textarea name="attendees">${esc((d.attendees||[]).join('\n'))}</textarea></label></div><label>${t('Punti discussi · uno per riga','Points abordés · un par ligne')}<textarea name="agenda">${esc((d.agenda||[]).join('\n'))}</textarea></label><label>${t('Decisioni · una per riga','Décisions · une par ligne')}<textarea name="decisions">${esc((d.decisions||[]).join('\n'))}</textarea></label></div>
      <div data-action-section ${n.kind==='free'?'hidden':''}><h3>${t('Attività / elenco','Actions / liste')}</h3><div id="nb-actions-list">${(d.actions||[]).map(actionRow).join('')}</div>${button(t('+ Aggiungi voce','+ Ajouter un élément'),'data-add-action')}</div>
      <p class="nb-help">${n.shared?t('Le modifiche salvate saranno visibili anche ai destinatari attuali.','Les modifications enregistrées seront visibles par les destinataires actuels.'):t('Salvare mantiene l’appunto privato. La condivisione è un passaggio separato.','Enregistrer conserve la note privée. Le partage est une étape distincte.')}</p>
      <div class="nb-actions"><button type="submit" class="nb-button nb-primary">${t('Salva appunto','Enregistrer la note')}</button><span id="nb-save-label" class="nb-help">${t('Nessuna modifica da salvare','Aucune modification à enregistrer')}</span></div></form>`:
      `<h2>${esc(n.title)}</h2><p class="nb-help">${esc(n.author)} · ${esc(date(n.updated_at))}</p>${n.site?`<p class="nb-context">${n.site_id?`<a href="/appunti?cantiere=${n.site_id}">${esc(n.site)}</a>`:esc(n.site)}</p>`:''}${readContent(n)}`)+
      (n.owner?`<div class="nb-actions">${button(n.shared?t('Gestisci accessi','Gérer les accès'):t('Condividi','Partager'),'data-sharing')}
        ${!n.archived?button(t('Riordina con AI','Réorganiser avec l’IA'),'data-ai')+button(t('Prepara verbale','Préparer un compte rendu'),'data-ai-meeting'):''}
        ${button(n.archived?t('Ripristina','Restaurer'):t('Archivia','Archiver'),'data-archive')}</div>
        <p class="nb-help">${t('Originali e proposte AI restano visibili solo a te.','Les versions précédentes et propositions IA restent visibles uniquement par vous.')}</p>
        <details id="nb-originals"><summary>${t('Versioni precedenti e originali','Versions précédentes et originaux')}</summary><div id="nb-history"></div></details>`:'')+
      draftHtml();
    const back=editor.querySelector('[data-back]');back.classList.add('nb-back');
    state.dirty=false;
  }
  function dirty(){state.dirty=true;const label=q('#nb-save-label');if(label)label.textContent=t('Modifiche da salvare','Modifications à enregistrer');}
  function payload() {
    const form=q('#nb-edit-form'),f=form.elements;
    const lines=name=>f[name].value.split('\n').map(v=>v.trim()).filter(Boolean);
    const actions=[...form.querySelectorAll('.nb-action-row')].map(row=>({text:row.querySelector('[data-action-text]').value.trim(),
      assignee:row.querySelector('[data-action-assignee]').value.trim(),due:row.querySelector('[data-action-due]').value.trim(),done:row.querySelector('[data-action-done]').checked})).filter(a=>a.text||a.assignee||a.due);
    return {title:f.title.value,kind:f.kind.value,body:f.body.value,version:state.current.version,
      site_id:f.site_id.value?Number(f.site_id.value):null,collection:f.collection?.value||'',
      details:{when:f.when.value,attendees:lines('attendees'),agenda:lines('agenda'),decisions:lines('decisions'),actions}};
  }
  async function openNote(id, expand=true) {
    const generation=++detailGeneration;
    try{
      const note=await api('/'+id);
      if(generation!==detailGeneration)return;
      state.current=note;state.draft=note.draft||null;aiKey=null;revisionOffset=0;setNoteUrl(note.id);
      renderEditor();renderList();
      if(expand)root.classList.add('nb-detail-open');
    }catch(err){if(generation===detailGeneration){state.current=null;state.draft=null;renderEditor();setNoteUrl(null);}throw err;}
  }
  function showDialog(title,content) {
    dialog.innerHTML=`<div class="nb-dialog-header"><h2 id="nb-dialog-title">${title}</h2>${button('×','data-close-dialog aria-label="'+t('Chiudi','Fermer')+'"')}</div>${content}<p class="nb-help" id="nb-dialog-error" role="alert"></p>`;
    dialog.showModal();
  }
  async function sharing() {
    const n=state.current,recipients=await api('/'+n.id+'/destinatari');
    showDialog(t('Chi può vederlo?','Qui peut voir cette note ?'),`<p>${esc(n.title)}</p><p class="nb-help">${t('Seleziona le persone. Il cantiere e i partecipanti non danno accesso automatico. Sarà condivisa la versione attuale, non gli originali.','Choisissez les personnes. Le chantier et les participants ne donnent aucun accès automatique. Seule la version actuelle est partagée, pas les originaux.')}</p><form id="nb-sharing-form"><div>${recipients.map(p=>{
      const grant=n.grants.find(g=>g.user_id===p.id);
      return `<div class="nb-person"><label class="nb-check"><input type="checkbox" data-recipient="${p.id}" ${grant?'checked':''}><span>${esc(p.name)}</span></label><select aria-label="${esc(t('Permesso per ','Autorisation pour ')+p.name)}" ${grant?'':'disabled'}>${option('read',t('Può leggere','Lecture'),grant?.permission)}${option('edit',t('Può modificare','Modification'),grant?.permission)}</select></div>`;
    }).join('')||`<p>${t('Non ci sono altri account attivi.','Aucun autre compte actif.')}</p>`}</div><p class="nb-help">${t('Nessuna persona selezionata = Solo io. Puoi revocare gli accessi in qualsiasi momento.','Aucune personne sélectionnée = Moi uniquement. Vous pouvez retirer les accès à tout moment.')}</p><div class="nb-actions"><button type="submit" class="nb-button nb-primary">${t('Conferma accessi','Confirmer les accès')}</button>${button(t('Rendi privato','Rendre privée'),'data-make-private')}</div></form>`);
  }
  function prepare(mode) {
    const n=state.current;
    if(n.shared){showDialog(t('Prima rendi privato l’appunto','Rendez d’abord la note privée'),`<p>${t('Il riordino si prepara su un appunto privato. Da “Gestisci accessi” puoi togliere la condivisione e riattivarla dopo la verifica.','La réorganisation se prépare sur une note privée. Retirez le partage dans « Gérer les accès », puis réactivez-le après vérification.')}</p>`);return;}
    if(!state.ai_enabled){showDialog(t('Riordino AI da attivare','Réorganisation IA à activer'),`<p>${t('La funzione richiede l’attivazione del servizio AI da parte dell’amministratore. Puoi già scrivere, organizzare e condividere gli appunti.','Cette fonction nécessite l’activation du service IA par l’administrateur. Vous pouvez déjà écrire, organiser et partager vos notes.')}</p>`);return;}
    // Each opened dialog is a new intent; retries within that dialog reuse its key.
    aiKey=crypto.randomUUID();
    showDialog(mode==='meeting'?t('Prepara una bozza di verbale','Préparer un compte rendu'):t('Riordina questo appunto','Réorganiser cette note'),
      `<p>${t('Il testo e le sezioni di questo appunto saranno inviati a OpenAI per preparare una proposta. L’originale resta conservato e nessun collega riceverà il risultato automaticamente.','Le texte et les sections de cette note seront envoyés à OpenAI pour préparer une proposition. L’original est conservé et aucun collègue ne reçoit automatiquement le résultat.')}</p><div class="nb-actions">${button(t('Prepara proposta privata','Préparer une proposition privée'),`data-prepare="${mode}"`,true)}</div>`);
  }
  async function save() {
    if(!q('#nb-edit-form')?.reportValidity())return false;
    const n=await api('/'+state.current.id,'PUT',payload());
    state.current=n;state.draft=n.draft||null;aiKey=null;renderEditor();await loadList();
    status(t('Appunto salvato.','Note enregistrée.'));return true;
  }
  async function guardSaved() {
    if(!state.dirty)return true;
    if(!confirm(t('Prima occorre salvare le modifiche. Salvare e continuare?','Enregistrez d’abord vos modifications. Enregistrer et continuer ?')))return false;
    return save();
  }
  async function run(action) {
    if(state.busy)return;
    const wasDialogOpen=dialog.open;
    state.busy=true;root.inert=true;dialog.inert=true;root.setAttribute('aria-busy','true');q('#nb-error').hidden=true;status('');
    try{await action();}catch(err){if(dialog.open)q('#nb-dialog-error').textContent=err.message;else error(err);}
    finally{state.busy=false;root.inert=false;dialog.inert=false;root.removeAttribute('aria-busy');root.querySelectorAll('[data-working]').forEach(b=>{b.disabled=false;b.removeAttribute('data-working');});if(!wasDialogOpen&&dialog.open)dialog.querySelector('button')?.focus();}
  }
  root.addEventListener('input',e=>{if(e.target.closest('#nb-edit-form'))dirty();});
  root.addEventListener('change',e=>{
    if(e.target.closest('#nb-edit-form')){
      dirty();
      if(e.target.name==='kind'){q('[data-meeting-fields]').hidden=e.target.value!=='meeting';q('[data-action-section]').hidden=e.target.value==='free';}
    }
    if(e.target.matches('[data-recipient]'))e.target.closest('.nb-person').querySelector('select').disabled=!e.target.checked;
    if(e.target.matches('#nb-site-filter,#nb-collection-filter'))run(async()=>{
      if(!leave()){renderList();return;}state.site=q('#nb-site-filter').value;state.collection=q('#nb-collection-filter').value;state.offset=0;await loadList();state.current=null;state.draft=null;renderEditor();setNoteUrl(null);
    });
  });
  root.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.hasAttribute('data-close-dialog')){if(!state.busy)dialog.close();return;}
    if(b.hasAttribute('data-add-action')){q('#nb-actions-list').insertAdjacentHTML('beforeend',actionRow({text:'',done:false}));dirty();return;}
    if(b.hasAttribute('data-remove-action')){b.closest('.nb-action-row').remove();dirty();return;}
    if(b.hasAttribute('data-back')){if(leave()){state.dirty=false;root.classList.remove('nb-detail-open');state.current=null;state.draft=null;setNoteUrl(null);renderEditor();renderList();}return;}
    run(async()=>{
      if(b.dataset.note){if(leave())await openNote(Number(b.dataset.note));}
      else if(b.dataset.scope){if(!leave())return;state.scope=b.dataset.scope;state.offset=0;state.current=null;state.draft=null;setNoteUrl(null);root.classList.remove('nb-detail-open');renderEditor();await loadList();}
      else if(b.id==='nb-prev'||b.id==='nb-next'){if(!leave())return;state.offset=Math.max(0,state.offset+(b.id==='nb-next'?50:-50));await loadList();}
      else if(b.hasAttribute('data-new')){
        if(!leave())return;newKey=newKey||crypto.randomUUID();
        const n=await api('','POST',{title:t('Nuovo appunto','Nouvelle note'),kind:'free',site_id:state.site?Number(state.site):null,request_key:newKey});
        newKey=null;state.scope='mine';state.collection='';state.query='';q('#nb-search').value='';state.offset=0;
        await loadList();await openNote(n.id);q('[name=title]').focus();q('[name=title]').select();
      }else if(b.hasAttribute('data-sharing')){if(await guardSaved())await sharing();}
      else if(b.hasAttribute('data-ai')||b.hasAttribute('data-ai-meeting')){if(await guardSaved())prepare(b.hasAttribute('data-ai-meeting')?'meeting':'tidy');}
      else if(b.dataset.prepare){
        b.disabled=true;b.dataset.working='1';
        q('#nb-dialog-error').textContent=t('Sto preparando la proposta…','Préparation de la proposition…');
        state.draft=await api('/'+state.current.id+'/riordina','POST',{version:state.current.version,mode:b.dataset.prepare,request_key:aiKey,consent:true});
        dialog.close();renderEditor();q('.nb-draft').scrollIntoView({behavior:'smooth',block:'start'});status(t('Proposta pronta: ricontrollala prima di accettare.','Proposition prête : vérifiez-la avant de l’accepter.'));
      }else if(b.dataset.draftDecision){
        if(state.dirty){throw new Error(t('Salva le modifiche e prepara una nuova proposta.','Enregistrez les modifications puis préparez une nouvelle proposition.'));}
        const decision=b.dataset.draftDecision;
        state.current=await api(`/${state.current.id}/bozze/${state.draft.id}/${decision}`,'POST',{version:state.current.version});
        state.draft=null;aiKey=null;renderEditor();await loadList();status(decision==='accetta'?t('Bozza applicata. L’appunto è ancora privato e l’originale è conservato.','Brouillon appliqué. La note reste privée et l’original est conservé.'):t('Proposta scartata.','Proposition ignorée.'));
      }else if(b.hasAttribute('data-archive')){
        if(!await guardSaved())return;
        state.current=await api('/'+state.current.id+'/archivio','PUT',{version:state.current.version,archived:!state.current.archived});
        state.draft=null;renderEditor();await loadList();status(t('Archivio aggiornato. Gli accessi restano invariati.','Archives mises à jour. Les accès restent inchangés.'));
      }else if(b.hasAttribute('data-make-private')){
        state.current=await api('/'+state.current.id+'/condivisione','PUT',{version:state.current.version,grants:[],confirm:true});
        dialog.close();state.draft=null;renderEditor();await loadList();status(t('Appunto privato: solo tu puoi leggerlo.','Note privée : vous seul pouvez la lire.'));
      }else if(b.hasAttribute('data-more-history')){revisionOffset+=20;await historyRows(true);}
    });
  });
  root.addEventListener('submit',e=>{
    if(!e.target.matches('#nb-edit-form,#nb-filter-form,#nb-sharing-form'))return;e.preventDefault();
    run(async()=>{
      if(e.target.id==='nb-edit-form')await save();
      else if(e.target.id==='nb-filter-form'){if(!leave())return;state.query=q('#nb-search').value;state.offset=0;await loadList();}
      else{
        const grants=[...dialog.querySelectorAll('[data-recipient]:checked')].map(el=>({user_id:Number(el.dataset.recipient),permission:el.closest('.nb-person').querySelector('select').value}));
        state.current=await api('/'+state.current.id+'/condivisione','PUT',{version:state.current.version,grants,confirm:true});
        dialog.close();state.draft=null;renderEditor();await loadList();status(t('Accessi aggiornati.','Accès mis à jour.'));
      }
    });
  });
  async function historyRows(append=false) {
    const history=await api('/'+state.current.id+'/originali?offset='+revisionOffset);
    const html=history.revisions.map(r=>`<section class="nb-original"><h3>${t('Versione','Version')} ${r.version} · ${esc(date(r.created_at))}</h3><strong>${esc(r.content.title)}</strong>${readContent(r.content)}</section>`).join('')||`<p>${t('Non ci sono ancora versioni precedenti.','Aucune version précédente.')}</p>`;
    q('[data-more-history]')?.remove();
    if(append)q('#nb-history').insertAdjacentHTML('beforeend',html);else q('#nb-history').innerHTML=html;
    if(history.more)q('#nb-history').insertAdjacentHTML('beforeend',button(t('Versioni meno recenti','Versions plus anciennes'),'data-more-history'));
  }
  root.addEventListener('toggle',e=>{if(e.target.id==='nb-originals'&&e.target.open)run(()=>historyRows());},true);
  dialog.addEventListener('cancel',e=>{if(state.busy)e.preventDefault();});
  window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
  run(async()=>{await loadList();const id=Number(new URLSearchParams(location.search).get('note'));if(id)await openNote(id);else if(state.notes.length&&window.innerWidth>767)await openNote(state.notes[0].id,false);});
})();
