(() => {
  'use strict';
  const form = document.querySelector('.project-config-form');
  if (!form) return;
  const fr = document.documentElement.lang === 'fr';
  const t = (it, french) => fr ? french : it;
  const ns = 'http://www.w3.org/2000/svg';
  let elements = [], layout = null;
  const cards = () => [...form.querySelectorAll('[data-coupe-card]')];
  const input = card => card.querySelector('[name="coupe_paratie"]');
  const kind = card => card.querySelector('[name="coupe_tipologia_scavo"]').value;
  form.dataset.kind = 'paratia';
  function showKinds() {
    cards().forEach(card=>{
      card.hidden=kind(card)!==form.dataset.kind || (card.classList.contains('project-coupe-card--new')&&!card.dataset.started);
      card.querySelectorAll('[data-only-kind]').forEach(e=>e.hidden=kind(card)!=='mixed'&&e.dataset.onlyKind!==kind(card));
      const wallInput=input(card),pileInput=card.querySelector('[name=coupe_pali]');
      if(kind(card)==='paratia'&&elements.length&&!wallInput.hasAttribute('aria-invalid'))wallInput.closest('.project-field').hidden=true;
      if(kind(card)==='palo'&&wallInput.value.trim())wallInput.closest('.project-field').hidden=false;
      if(kind(card)==='paratia'&&pileInput.value.trim())pileInput.closest('.project-field').hidden=false;
      card.querySelector('.coupe-picker')?.toggleAttribute('hidden',kind(card)==='palo');
      card.querySelector('[data-association-heading]').textContent=kind(card)==='palo'?t('Pali di questa coupe','Pieux de cette coupe'):t('Pannelli di questa coupe','Panneaux de cette coupe');
    });
    document.querySelectorAll('[data-coupe-kind]').forEach(b=>{
      b.setAttribute('aria-pressed',String(b.dataset.coupeKind===form.dataset.kind));
      if(b.dataset.coupeKind==='mixed')b.hidden=!cards().some(c=>kind(c)==='mixed');
    });
  }
  document.querySelectorAll('[data-coupe-kind]').forEach(b=>b.onclick=()=>{form.dataset.kind=b.dataset.coupeKind;showKinds();});
  function numbers(value) {
    const result = new Set();
    value.split(/[,;\s]+/).filter(Boolean).forEach(token => {
      const parts = token.split('-').map(Number);
      if (parts.every(n => Number.isInteger(n) && n > 0 && n <= 10000))
        for (let n = parts[0]; n <= (parts[1] || parts[0]); n++) result.add(n);
    });
    return result;
  }
  const owner = (card, n) => cards().find(c => c !== card && !c.querySelector('[name="delete_coupe_id"]')?.checked && numbers(input(c).value).has(n));
  function toggle(card, n) {
    if (owner(card,n)) return;
    const selected = numbers(input(card).value);
    if (selected.has(n)) selected.delete(n); else selected.add(n);
    input(card).value = [...selected].sort((a,b)=>a-b).join(',');
    refresh();
  }
  function refresh() {
    cards().forEach(card => {
      const selected = numbers(input(card).value);
      card.querySelector('[data-selection-summary]').textContent = kind(card)==='palo'?`${numbers(card.querySelector('[name=coupe_pali]').value).size} ${t('pali','pieux')}`:`${selected.size} ${selected.size === 1 ? t('pannello','panneau') : t('pannelli','panneaux')}`;
      card.querySelectorAll('[data-panel-number]').forEach(button => {
        const n = +button.dataset.panelNumber, other = owner(card,n), active = selected.has(n);
        button.classList.toggle('selected', active);
        button.classList.toggle('occupied', !!other);
        button.setAttribute('aria-pressed', String(active));
        button.setAttribute('aria-disabled', String(!!other));
        if (button.tagName === 'BUTTON') button.disabled = !!other;
        const name = other?.querySelector('[name="coupe_nome"]').value || t('altra coupe','autre coupe');
        button.setAttribute('aria-label', `${button.dataset.label}${other ? ` · ${t('assegnato a','affecté à')} ${name}` : ''}`);
      });
    });
  }
  function build(card) {
    card.querySelector('.coupe-picker')?.remove();
    const section = card.querySelector('.coupe-associations');
    const picker = document.createElement('div'); picker.className = 'coupe-picker';
    const toolbar = document.createElement('div'); toolbar.className = 'coupe-picker-toolbar';
    const search = document.createElement('input'); search.type='search'; search.className='form-control'; search.placeholder=t('Cerca pannello','Rechercher un panneau'); search.setAttribute('aria-label',t('Cerca pannello','Rechercher un panneau'));
    const select = document.createElement('button'); select.type='button'; select.className='btn btn-secondary'; select.textContent=t('Seleziona disponibili','Sélectionner les disponibles');
    const clear = document.createElement('button'); clear.type='button'; clear.className='btn btn-secondary'; clear.textContent=t('Deseleziona','Désélectionner');
    toolbar.append(search,select,clear); picker.append(toolbar);
    if (layout?.panels.length) {
      const points=layout.panels.flatMap(p=>p.points), xs=points.map(p=>p[0]), ys=points.map(p=>p[1]);
      const x=Math.min(...xs)-20,y=Math.min(...ys)-20,w=Math.max(...xs)-x+20,h=Math.max(...ys)-y+20;
      const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`${x} ${y} ${w} ${h}`);svg.classList.add('coupe-plan');svg.setAttribute('aria-label',t('Selezione pannelli dalla pianta','Sélection des panneaux sur le plan'));
      layout.panels.forEach(p=>{
        if(!p.element)return;
        const g=document.createElementNS(ns,'g');g.dataset.panelNumber=p.element;g.dataset.label=p.label;g.setAttribute('role','button');g.setAttribute('tabindex','0');
        const polygon=document.createElementNS(ns,'polygon');polygon.setAttribute('points',p.points.map(v=>v.join(',')).join(' '));g.append(polygon);
        const text=document.createElementNS(ns,'text');text.setAttribute('x',p.points.reduce((s,v)=>s+v[0],0)/4);text.setAttribute('y',p.points.reduce((s,v)=>s+v[1],0)/4);text.setAttribute('font-size',Math.max(7,w/90));text.textContent=p.label;g.append(text);
        g.onclick=()=>toggle(card,p.element);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(card,p.element);}};svg.append(g);
      });picker.append(svg);
    }
    const grid=document.createElement('div');grid.className='coupe-panel-grid';
    elements.forEach(e=>{const button=document.createElement('button');button.type='button';button.dataset.panelNumber=e.number;button.dataset.label=e.label;button.textContent=e.label;button.onclick=()=>toggle(card,e.number);grid.append(button);});picker.append(grid);
    const note=document.createElement('small');note.textContent=t('Selezionati in rosso. I pannelli assegnati ad altre coupe sono disabilitati.','Sélection en rouge. Les panneaux affectés à une autre coupe sont désactivés.');picker.append(note);
    section.insertBefore(picker,section.querySelector('.form-grid'));
    input(card).closest('.project-field').hidden=elements.length>0&&!input(card).hasAttribute('aria-invalid');
    search.oninput=()=>grid.querySelectorAll('button').forEach(b=>b.hidden=!b.textContent.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()));
    select.onclick=()=>{const chosen=numbers(input(card).value);grid.querySelectorAll('button:not([hidden])').forEach(b=>{if(!owner(card,+b.dataset.panelNumber))chosen.add(+b.dataset.panelNumber);});input(card).value=[...chosen].sort((a,b)=>a-b).join(',');refresh();};
    clear.onclick=()=>{input(card).value='';refresh();};
    refresh(); showKinds();
  }
  form.addEventListener('input',e=>{const card=e.target.closest('[data-coupe-card]');if(card)card.dataset.started='1';refresh();});
  form.addEventListener('change',e=>{
    if(e.target.name!=='coupe_tipologia_scavo')return;
    const card=e.target.closest('[data-coupe-card]');form.dataset.kind=kind(card);
    // Keep entered assignments visible until the user explicitly clears them.
    showKinds();refresh();
    const wrong=card.querySelector(kind(card)==='palo'?'[name=coupe_paratie]':'[name=coupe_pali]');
    if(wrong.value.trim())wrong.closest('.project-field').hidden=false;
  });
  form.addEventListener('invalid',e=>{const details=e.target.closest('.coupe-editor');if(details)details.open=true;},true);
  document.addEventListener('coupe-added',e=>build(e.detail));
  const errors=JSON.parse(document.getElementById('coupe-field-errors')?.textContent||'[]');
  if(errors.length&&cards()[errors[0].row])form.dataset.kind=kind(cards()[errors[0].row]);
  errors.forEach(error=>{
    const card=cards()[error.row], field=card?.querySelector(`[name="${error.field}"]`);
    if(!field)return;
    card.hidden=false;card.querySelector('.coupe-editor').open=true;
    for(let parent=field.parentElement;parent&&parent!==card;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}
    field.id=`coupe-field-${error.row}-${error.field}`;field.setAttribute('aria-invalid','true');
    const message=document.createElement('p');message.className='coupe-field-error';message.id=field.id+'-error';message.textContent=fr?error.fr:error.it;
    field.setAttribute('aria-describedby',message.id);field.after(message);
  });
  const equipment=JSON.parse(document.getElementById('coupe-equipment-values')?.textContent||'{}');
  form.querySelectorAll('.project-equipment-row:not(.project-equipment-row--head)').forEach(row=>{
    const i=(equipment.equipment_numero||[]).findIndex((n,index)=>n===row.querySelector('[name="equipment_numero"]').value&&equipment.equipment_tipologia[index]===row.querySelector('[name="equipment_tipologia"]').value);
    if(i>=0)row.querySelector('[name="equipment_mode"]').value=equipment.equipment_mode[i];
  });
  document.getElementById('coupe-errors')?.focus();
  cards().forEach(card=>{if(!card.hidden)card.dataset.started='1';});
  showKinds();
  fetch(`/manager/cantieri/${form.dataset.site}/pianta/data`,{credentials:'same-origin'}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{
    elements=data.elements.sort((a,b)=>a.label.localeCompare(b.label,fr?'fr':'it',{numeric:true,sensitivity:'base'})||a.number-b.number);layout=data.plan&&!data.plan.editing?data.plan.layout:null;
    cards().forEach(build);
    form.querySelectorAll('.project-equipment-row:not(.project-equipment-row--head)').forEach(row=>{if(row.querySelector('[name="equipment_tipologia"]').value==='paratia'){const n=+row.querySelector('[name="equipment_numero"]').value;row.querySelector('span').textContent=elements.find(e=>e.number===n)?.label||n;}});
  }).catch(()=>{cards().forEach(card=>card.querySelector('[data-selection-summary]').textContent=t('Inserisci i numeri nei campi associazione','Saisissez les numéros dans les champs d’affectation'));});
})();
