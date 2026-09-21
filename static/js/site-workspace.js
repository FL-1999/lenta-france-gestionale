/* Cantiere: approved geometry only. Production mutations require confirmation. */
(() => {
  const root = document.getElementById('site-workspace'); if (!root) return;
  const data = JSON.parse(document.getElementById('sw-plan-data').textContent);
  let groups = JSON.parse(document.getElementById('sw-pours-data').textContent);
  const site = root.dataset.site, canEdit = root.dataset.edit === 'true';
  const base = `/manager/cantieri/${site}`, selected = new Set();
  const q = s => root.querySelector(s), esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = v => v == null ? '—' : Number(v).toLocaleString('it-IT',{maximumFractionDigits:3});
  const message = s => { q('#sw-message').textContent = s; };
  const elements = new Map(data.elements.map(e => [e.number,e]));
  const panels = data.plan?.approved_at && !data.plan.editing ? data.plan.layout.panels : [];
  const editor = html => {q('#sw-editor-body').innerHTML=html;q('#sw-group-editor').hidden=false;q('#sw-group-editor').scrollIntoView({block:'nearest'});};
  async function api(path,method,body) {
    const response=await fetch(base+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    const result=await response.json().catch(()=>({detail:'Risposta non valida. Ricarica la pagina.'}));
    if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Controlla i valori inseriti.');
    return result;
  }
  function selectPanel(n) {
    if(q('#sw-multi')?.checked) { selected.has(n)?selected.delete(n):selected.add(n); }
    else { selected.clear(); selected.add(n); }
    root.querySelectorAll('[data-panel]').forEach(node=>node.setAttribute('aria-pressed',selected.has(Number(node.dataset.panel))));
    if(q('#sw-selected')) q('#sw-selected').textContent=[...selected].map(i=>elements.get(i)?.label||i).join(' + ');
    const e=elements.get(n); if(!e)return;
    const g=groups.find(g=>g.members.some(m=>m.number===n));
    const shared=g?.kind==='angle';
    q('#sw-panel-detail').innerHTML=`<div class="sw-row"><div><strong>${esc(e.label)}</strong><div class="sw-muted">${esc(e.coupe||'CUP da assegnare')} · ${e.status==='cast'?'Gettato':e.fiche_id?'Fiche presente':'Da eseguire'}${e.concrete_m3==null?'':` · ${number(e.concrete_m3)} m³${shared?' · totale angolo':''}`}</div></div>${e.fiche_url?`<a class="btn btn-secondary" href="${esc(e.fiche_url)}">Apri fiche${shared?' unica':''}</a>`:e.create_url?`<a class="btn btn-primary" href="${esc(e.create_url)}">Crea fiche${shared?' unica':''}</a>`:''}</div>`;
  }
  function draw() {
    if(!panels.length){q('#sw-plan').innerHTML=`<p style="padding:20px">Nessuna pianta convalidata. <a href="${base}/pianta">Carica o controlla il PDF</a>.</p>`;return;}
    const pts=panels.flatMap(p=>p.points),xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
    const x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y,pad=Math.max(w,h)*.05;
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox',`${x-pad} ${y-pad} ${w+2*pad} ${h+2*pad}`);svg.setAttribute('aria-label','Pianta convalidata: seleziona un pannello');
    panels.forEach(p=>{const e=elements.get(p.element);if(!e)return;const polygon=document.createElementNS(ns,'polygon');polygon.setAttribute('points',p.points.map(v=>v.join(',')).join(' '));polygon.classList.add('sw-panel');polygon.dataset.panel=p.element;polygon.dataset.status=e.status;polygon.setAttribute('role','button');polygon.setAttribute('tabindex','0');polygon.setAttribute('aria-label',p.label);polygon.setAttribute('aria-pressed','false');svg.append(polygon);const text=document.createElementNS(ns,'text');text.classList.add('sw-plan-label');text.setAttribute('x',p.points.reduce((s,v)=>s+v[0],0)/4);text.setAttribute('y',p.points.reduce((s,v)=>s+v[1],0)/4);text.setAttribute('text-anchor','middle');text.setAttribute('dominant-baseline','central');text.setAttribute('font-size',Math.max(w,h)*.018);text.textContent=p.label;svg.append(text);});
    q('#sw-plan').replaceChildren(svg);
    const list=document.createElement('div');list.className='sw-panel-list';list.setAttribute('aria-label','Selezione pannelli');list.innerHTML=panels.map(p=>`<button type="button" class="btn btn-secondary btn-sm" data-panel="${p.element}" aria-pressed="false">${esc(p.label)}</button>`).join('');q('#sw-plan').append(list);
    q('#sw-original').href=data.plan.original_url;q('#sw-original').hidden=false;
  }
  function renderGroups() {
    q('#sw-groups').innerHTML=groups.length?groups.map(g=>`<div class="sw-list-row"><div><strong>${esc(g.label)}</strong><div class="sw-muted">${g.kind==='angle'?'Angolo · fiche unica':'Getto congiunto · fiches separate'}${g.total_m3==null?' · da registrare':` · ${number(g.total_m3)} m³`}</div></div><button type="button" class="btn btn-secondary" data-group="${g.id}">${canEdit?'Apri / modifica':'Apri'}</button></div>`).join(''):'<p class="sw-muted">Seleziona i pannelli sulla pianta per creare un angolo o un getto congiunto.</p>';
  }
  function openGroup(id) {
    const g=groups.find(g=>g.id===id);if(!g)return;
    editor(`<div class="sw-row"><h2>${esc(g.label)}</h2><button type="button" class="btn btn-secondary" data-close-editor>Chiudi</button></div><p>${g.kind==='angle'?'Una fiche per i due bracci. Larghezze nette confermate; il disegno della fiche mostra lo sviluppo complessivo.':'Compila le fiches dei singoli pannelli, poi registra una sola volta data e volume del getto.'}</p>${g.members.map(m=>`<div class="sw-list-row"><span>${esc(m.label)} · ${number(m.width)} × ${number(m.depth)} × ${number(m.thickness)} m</span><a class="btn btn-secondary" href="${m.fiche_id?`/manager/fiches/${m.fiche_id}`:`/manager/fiches/nuova?cantiere_id=${site}&numero_pannello=${m.number}&tipologia_scavo=paratia`}">${m.fiche_id?'Apri fiche':'Crea fiche'}</a></div>`).join('')}${canEdit&&g.kind==='joint'?`<form id="sw-cast-form" data-group-id="${g.id}"><div class="sw-editor-grid"><label>Data getto<input type="date" name="cast_date" required value="${g.cast_date||''}"></label><label>Calcestruzzo totale · m³<input type="number" step="0.001" min="0.001" max="100000" name="total_m3" required value="${g.total_m3??''}"></label></div><label><input type="checkbox" name="manual"> Modifica manualmente la ripartizione</label><div id="sw-allocation"></div><p class="sw-muted">Ripartizione stimata sui volumi teorici; a profondità e spessore uguali è proporzionale alle larghezze.</p><button type="submit" class="btn btn-primary">Conferma getto e quantità</button></form>`:''}${canEdit?`<div class="sw-list-row"><span class="sw-muted">Per cambiare pannelli: sciogli il gruppo e ricrealo.</span><button type="button" class="btn btn-danger" data-remove-group="${g.id}">Sciogli gruppo</button></div>`:''}`);
    const form=q('#sw-cast-form');if(form){form.addEventListener('input',()=>preview(g,form));preview(g,form);form.addEventListener('submit',async e=>{e.preventDefault();const total=Number(form.elements.total_m3.value),manual=form.elements.manual.checked?[...form.querySelectorAll('[data-allocation]')].map(i=>Number(i.value)):null;if(!confirm('Confermare il totale e aggiornare le quantità delle fiches selezionate?'))return;const submit=form.querySelector('[type=submit]');submit.disabled=true;try{await api('/getti/'+g.id,'PUT',{revision:g.revision,total_m3:total,cast_date:form.elements.cast_date.value,manual,confirm:true});location.reload();}catch(err){message(err.message);submit.disabled=false;}});}
  }
  function preview(g,form){
    if(form.elements.manual.checked&&q('#sw-allocation input')){form.querySelectorAll('[data-allocation]').forEach(i=>i.disabled=false);return;}
    const total=Number(form.elements.total_m3.value)||0,weights=g.members.map(m=>m.width*m.depth*m.thickness),sum=weights.reduce((a,b)=>a+b,0),units=Math.round(total*1000),raw=weights.map(w=>units*w/sum),parts=raw.map(Math.floor);let rest=units-parts.reduce((a,b)=>a+b,0);[...raw.keys()].sort((a,b)=>(raw[b]-parts[b])-(raw[a]-parts[a])).slice(0,rest).forEach(i=>parts[i]++);
    q('#sw-allocation').innerHTML=g.members.map((m,i)=>`<label class="sw-list-row"><span>${esc(m.label)} · ${number(weights[i]/sum*100)}%</span><input class="form-control" aria-label="Quantità ${esc(m.label)}" type="number" min="0" step="0.001" data-allocation value="${parts[i]/1000}" ${form.elements.manual.checked?'':'disabled'}> m³</label>`).join('');
  }
  root.addEventListener('keydown',e=>{if(e.target.matches('.sw-panel')&&['Enter',' '].includes(e.key)){e.preventDefault();selectPanel(Number(e.target.dataset.panel));}});
  root.addEventListener('click',async e=>{
    const p=e.target.closest('[data-panel]');if(p){selectPanel(Number(p.dataset.panel));return;}
    const a=e.target.closest('a[href="#sw-fiches"]');if(a)q('#sw-fiches').open=true;
    const open=e.target.closest('[data-group]');if(open){openGroup(Number(open.dataset.group));return;}
    if(e.target.closest('[data-close-editor]')){q('#sw-group-editor').hidden=true;return;}
    const create=e.target.closest('[data-make-group]');if(create){
      const kind=create.dataset.makeGroup;
      if(kind==='angle'&&selected.size===1){const n=[...selected][0],label=elements.get(n)?.label||'',match=label.match(/^(.*?)\s*([ab])$/i);if(match){const candidates=panels.filter(p=>p.element!==n&&p.label.trim().toLowerCase().replace(/\s/g,'')===(match[1]+(match[2].toLowerCase()==='a'?'b':'a')).toLowerCase().replace(/\s/g,''));if(candidates.length===1)selected.add(candidates[0].element);}}
      if(selected.size<2){message('Seleziona almeno due pannelli, oppure un braccio A/B per individuare il suo compagno.');return;}
      const labels=[...selected].map(n=>elements.get(n)?.label||n).join(' + ');
      const prompt=kind==='angle'?`Creare l’angolo ${labels}? Confermi che le larghezze dei due bracci sono nette, senza contare due volte l’intersezione?`:`Raggruppare ${labels} in un getto congiunto? Le fiches rimangono separate.`;
      if(!confirm(prompt))return;create.disabled=true;
      try{const g=await api('/getti','POST',{numbers:[...selected],kind,confirm_net:kind==='angle'});groups.push(g);renderGroups();openGroup(g.id);message('Gruppo salvato.');}catch(err){message(err.message);}finally{create.disabled=false;}return;
    }
    const remove=e.target.closest('[data-remove-group]');if(remove){const g=groups.find(g=>g.id===Number(remove.dataset.removeGroup));const hasFiche=g.members.some(m=>m.fiche_id);const warning=g.kind==='angle'&&hasFiche?'Verrà eliminata definitivamente anche la fiche unica dell’angolo. I pannelli rimarranno nella pianta.':'Le fiches rimangono; per il getto congiunto saranno ripristinate quantità e date precedenti alla ripartizione.';if(!confirm('Sciogliere il gruppo? '+warning))return;remove.disabled=true;try{await api(`/getti/${g.id}?revision=${g.revision}&confirm=true&delete_fiche=${g.kind==='angle'&&hasFiche}`,'DELETE');location.reload();}catch(err){message(err.message);remove.disabled=false;}}
  });
  draw();renderGroups();
})();
