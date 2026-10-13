(() => {
  const load=document.getElementById('load-planned-team'), area=document.getElementById('planned-team');
  if(!load)return;
  const fr=document.documentElement.lang==='fr',t=(it,french)=>fr?french:it;
  let roster,site,day;
  load.addEventListener('click',async()=>{
    site=document.getElementById('cantiere_id').value;day=document.getElementById('data').value;
    if(!site||!day){area.textContent=t('Scegli prima data e cantiere.','Choisissez la date et le chantier.');return;}
    try{const r=await fetch(`/capo/squadra?site_id=${site}&day=${day}`);if(!r.ok)throw new Error(t('Squadra non disponibile.','Équipe indisponible.'));roster=await r.json();
      area.innerHTML=`<div class="card" style="padding:16px;margin-top:16px"><strong>${escapeHtml(roster.team||t('Nessuna squadra assegnata','Aucune équipe affectée'))}</strong><p>${t('Seleziona i presenti. Il cambio vale solo per questo rapportino; puoi scegliere altre persone nelle righe sotto.','Sélectionnez les présents. Le changement vaut uniquement pour ce rapport ; vous pouvez choisir d’autres personnes ci-dessous.')}</p>${roster.people.filter(p=>p.id!==CAPOSQUADRA.id).map(p=>`<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 0"><label style="display:flex;gap:8px;align-items:center"><input type="checkbox" data-roster-person="${p.id}" ${p.unavailable?'disabled':'checked'}>${escapeHtml(p.name)} ${p.unavailable?' · '+t('Indisponibile','Indisponible'):''}</label>${p.unavailable?'':`<button type="button" class="btn btn-secondary" data-absent="${p.id}">${t('Segnala assenza','Signaler absent')}</button>`}</div>`).join('')}<button type="button" class="btn btn-primary" id="apply-planned-team">${t('Usa i presenti nel rapportino','Utiliser les présents dans le rapport')}</button></div>`;
    }catch(e){area.textContent=e.message;}
  });
  area.addEventListener('click',async e=>{
    if(site!==document.getElementById('cantiere_id').value||day!==document.getElementById('data').value){area.textContent=t('Data o cantiere cambiati: ricarica la squadra.','Date ou chantier modifié : rechargez l’équipe.');return;}
    const absent=e.target.closest('[data-absent]');
    if(absent){if(!confirm(t('Inviare all’ufficio la segnalazione di assenza per questa giornata?','Envoyer au bureau un signalement d’absence pour cette journée ?')))return;
      absent.disabled=true;
      try{const r=await fetch('/capo/squadra/assenza',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':roster.csrf},body:JSON.stringify({site_id:Number(site),person_id:Number(absent.dataset.absent),day,submission_key:crypto.randomUUID()})});if(!r.ok){const result=await r.json();throw new Error(result.detail||t('Invio non riuscito','Échec de l’envoi'));}load.click();}catch(err){alert(err.message);absent.disabled=false;}return;}
    if(e.target.id==='apply-planned-team'){
      const people=Array.from(area.querySelectorAll('[data-roster-person]:checked')).map(el=>Number(el.dataset.rosterPerson));
      if(people.length>9){alert(t('Seleziona fino a 9 persone oltre al caposquadra.','Sélectionnez jusqu’à 9 personnes en plus du chef d’équipe.'));return;}
      if(!confirm(t('Sostituire l’elenco persone del rapportino con i presenti selezionati? Attività e note restano invariate.','Remplacer les personnes du rapport par les présents sélectionnés ? Les activités et notes restent inchangées.')))return;
      workerCountInput.value=String(people.length+1);
      workersContainer.replaceChildren(buildCapoRow(readPreviousCapoRow()),...people.map(id=>buildWorkerRow({personale_id:id})));
      validateIncompleteDays();document.getElementById('rapportino-form').dispatchEvent(new Event('change',{bubbles:true}));
      area.textContent=t('Squadra caricata: controlla ore e persone prima di inviare.','Équipe chargée : vérifiez les heures et personnes avant l’envoi.');
    }
  });
})();
