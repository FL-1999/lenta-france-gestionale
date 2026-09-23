/* Original PDFs and confirmed layouts stay independent of editable proposals. */
(() => {
  'use strict';
  const root = document.getElementById('site-plan-app');
  if (!root) return;
  const q = s => root.querySelector(s), all = s => [...root.querySelectorAll(s)];
  const base = `/manager/cantieri/${root.dataset.site}/pianta`, ns = 'http://www.w3.org/2000/svg';
  const fr = document.documentElement.lang === 'fr';
  const t = (it, french) => fr ? french : it;
  const tr = text => window.LentaText(text);
  let snapUndo=null;
  let editUndo=[];
  let replacement=null;
  function ask(title,text,action=tr('Conferma')) {
    const dialog=q('[data-confirm-dialog]');
    q('#sp-confirm-title').textContent=title;q('#sp-confirm-text').textContent=text;
    q('[data-confirm-action]').textContent=action;dialog.returnValue='';
    return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});
  }
  const widthLocked=()=>q('[data-lock-width]').checked;
  const directionLocked=()=>q('[data-lock-direction]').checked;
  const peers=p=>p?.corner_group?plan.layout.panels.filter(v=>v.corner_group===p.corner_group):p?[p]:[];
  const units=()=>window.PlanGeometry.units(plan.layout.panels);
  const unitFor=p=>units().find(u=>u.members.some(v=>v.key===p?.key));
  function checkpoint(){editUndo.push(JSON.stringify(plan.layout));if(editUndo.length>25)editUndo.shift();}
  function invalidate(p){p.reviewed=false;p.extent_confirmed=false;peers(p).forEach(v=>{v.corner_net_confirmed=false;v.reviewed=false;});}
  const form = q('[data-editor]');
  let data, plan, selected, editing = false, dirty = false, busy = false, showOriginal = true, box, drag, addMode = false;
  function commonScale() {
    if(plan.layout.scale_ppm) return plan.layout.scale_ppm;
    const values=plan.layout.panels.filter(p=>p.width_m&&p.recognition==='edges').map(p=>geometry(p).len/p.width_m).sort((a,b)=>a-b);
    return values.length ? (values[Math.floor((values.length-1)/2)]+values[Math.floor(values.length/2)])/2 : null;
  }
  function extent(p) {
    if(p.points.some(([x,y])=>x<0||y<0||x>plan.layout.width||y>plan.layout.height))return true;
    const ref=p.reference_points;if(!ref)return false;
    const area=ref.reduce((sum,a,i)=>sum+a[0]*ref[(i+1)%4][1]-ref[(i+1)%4][0]*a[1],0),sign=area>=0?1:-1;
    return p.points.some(([x,y])=>ref.some((a,i)=>{const b=ref[(i+1)%4],len=Math.hypot(b[0]-a[0],b[1]-a[1]);return len&&sign*((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])) < -2*len;}));
  }
  function offScale(p) {const scale=commonScale();return !scale||!p.width_m||[[0,1],[3,2]].some(([i,j])=>Math.abs(Math.hypot(p.points[j][0]-p.points[i][0],p.points[j][1]-p.points[i][1])/(scale*p.width_m)-1)>.02);}
  function resize(p,anchor='center') {
    const scale=commonScale();if(!scale||!p.width_m)return false;
    const g=geometry(p),change=p.width_m*scale-g.len,a=g.angle*Math.PI/180;
    if(anchor!=='center'){const direction=anchor==='start'?1:-1;g.cx+=direction*change/2*Math.cos(a);g.cy+=direction*change/2*Math.sin(a);}
    g.len=p.width_m*scale;return updatePoints(p,rectangle(g));
  }
  function message(text, error = false) { q('[data-message]').textContent = text; q('[data-message]').dataset.error = error; }
  function markDirty() { dirty = true; renderFooter(); }
  function panel() { return plan?.layout.panels.find(p => p.key === selected); }
  function element(p) { return data?.elements.find(e => e.number === p?.element); }
  function num(v, unit = '') { return v == null ? '—' : `${Number(v).toLocaleString(fr?'fr-FR':'it-IT', {maximumFractionDigits: 2})}${unit}`; }
  function svgEl(tag, attrs = {}, text) { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v)); if (text != null) n.textContent = text; return n; }
  async function api(url, options = {}) {
    const res = await fetch(url, {credentials: 'same-origin', ...options});
    if (!res.headers.get('content-type')?.includes('application/json')) throw new Error(tr("Sessione scaduta: accedi di nuovo prima di salvare."));
    const payload = await res.json();
    if (!res.ok) throw new Error(typeof payload.detail === 'string' ? tr(payload.detail) : tr("Dati non validi. Controlla misure e campi."));
    return payload;
  }
  async function guard() { return !dirty || await ask(t('Modifiche non salvate','Modifications non enregistrées'),tr("Ci sono modifiche non salvate. Vuoi abbandonarle?")); }
  async function load(id, draft = false) {
    try {
      data = await api(base + '/data' + (id ? `?plan_id=${id}&draft=${draft}` : ''));
      snapUndo=null; editUndo=[]; plan = data.plan; editing = !!plan?.editing; dirty = false; addMode = false;
      replacement=null;if(q('[data-replace-notice]'))q('[data-replace-notice]').hidden=true;
      q('[data-removed]').hidden=!data.removed?.length;
      const removedList=q('[data-removed-list]');removedList.replaceChildren();
      (data.removed||[]).forEach(v=>{
        const row=document.createElement('div'),name=document.createElement('span'),button=document.createElement('button');
        row.className='sp-removed-row';name.textContent=v.filename;button.type='button';button.className='btn btn-secondary';button.textContent=t('Ripristina','Restaurer');
        button.onclick=async()=>{if(busy||!await guard())return;lock(true);try{await api(`${base}/${v.id}/ripristina`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:v.revision})});await load(v.id,true);}catch(e){message(tr(e.message),true);}finally{lock(false);}};
        row.append(name,button);removedList.append(row);
      });
      const versions = q('[data-version]'); versions.replaceChildren();
      data.versions.forEach(v => versions.add(new Option(`#${v.id} · ${v.filename} · ${v.approved ? t('convalidata','validé') : t('bozza','brouillon')}${v.approved && v.has_draft ? t(' + modifiche in bozza',' + modifications en brouillon') : ''}`, v.id)));
      q('[data-empty]').hidden = !!plan; q('[data-workspace]').hidden = !plan;
      if (!plan) { message(tr("Carica un PDF per preparare la pianta del cantiere.")); if (q('[data-upload]')) q('[data-upload]').hidden = false; return; }
      versions.value = plan.id; selected = plan.layout.panels[0]?.key; showOriginal = editing;
      q('[data-pdf]').href = plan.original_url; q('[data-page]').textContent = `${t('Pagina','Page')} ${plan.page_number}`;
      const image = q('[data-preview]'); image.setAttribute('href', plan.preview_url); image.setAttribute('width', plan.layout.width); image.setAttribute('height', plan.layout.height);
      const links = form.elements.element; links.replaceChildren(new Option(tr("Crea pannello alla convalida"), ''));
      data.elements.forEach(e => links.add(new Option(`${e.label} · ${t('elemento','élément')} ${e.number}${e.fiche_id ? t(' · fiche presente',' · fiche disponible') : ''}`, e.number)));
      plan.layout.panels.forEach(p => {p.reference_points ||= p.points.map(v=>[...v]);});
      plan.layout.scale_ppm=commonScale();
      fit(); render();
      message(editing ? tr(plan.layout.notice) : tr("Disegno convalidato. Avanzamento e dati provengono dalle fiches collegate."));
    } catch (error) { message(error.message, true); }
  }
  function fit() {
    const points = plan.layout.panels.flatMap(p => p.points);
    if (!points.length) { box = [0,0,plan.layout.width,plan.layout.height]; return; }
    const xs = points.map(p=>p[0]), ys = points.map(p=>p[1]);
    const x = Math.min(...xs), y = Math.min(...ys), w = Math.max(...xs)-x, h = Math.max(...ys)-y;
    box = [x-35,y-35,w+70,h+70];
  }
  function geometry(p) {
    const pts = p.points, cx = pts.reduce((s,v)=>s+v[0],0)/4, cy = pts.reduce((s,v)=>s+v[1],0)/4;
    return {cx,cy,len:Math.hypot(pts[1][0]-pts[0][0],pts[1][1]-pts[0][1]),depth:Math.hypot(pts[2][0]-pts[1][0],pts[2][1]-pts[1][1]),angle:Math.atan2(pts[1][1]-pts[0][1],pts[1][0]-pts[0][0])*180/Math.PI};
  }
  function rectangle(g) {
    const a = g.angle*Math.PI/180, ux = Math.cos(a), uy = Math.sin(a);
    return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([u,v])=>[g.cx+u*g.len/2*ux-v*g.depth/2*uy,g.cy+u*g.len/2*uy+v*g.depth/2*ux]);
  }
  function inBounds(points) { return points.every(([x,y]) => Number.isFinite(x)&&Number.isFinite(y)&&x>=-plan.layout.width&&y>=-plan.layout.height&&x<=2*plan.layout.width&&y<=2*plan.layout.height); }
  function updatePoints(p, points) { if (!points||!inBounds(points)) return false; p.points = points; invalidate(p); markDirty(); return true; }
  function renderMaps() {
    if (!plan) return;
    all('.sp-board svg').forEach(svg=>svg.setAttribute('viewBox', box.join(' ')));
    const groups = [q('[data-original-shapes]'),q('[data-clean-shapes]')]; groups.forEach(g=>g.replaceChildren());
    const displayUnits=units(),drawn=new Set();
    [...plan.layout.panels].sort((a,b)=>Number(a.key===selected)-Number(b.key===selected)).forEach(p => {
      const unit=displayUnits.find(u=>u.members.includes(p)),corner=unit.members.length===2,merged=corner&&unit.outline;
      const e = element(p), active = p.key === selected,related=!active&&panel()?.corner_group&&p.corner_group===panel().corner_group;
      groups.forEach((group,i) => {
        if(merged&&!drawn.has(unit)){
          const selectedUnit=unit.members.some(v=>v.key===selected);
          const outline=svgEl('path',{d:'M'+unit.outline.map(v=>v.join(',')).join('L')+'Z',class:`sp-panel sp-unified ${e?.status||'planned'} ${selectedUnit?'selected':''}`,'data-key':selectedUnit?selected:unit.members[0].key,'data-angle':p.corner_group,opacity:editing&&!selectedUnit?+q('[data-neighbour-opacity]').value/100:1});
          outline.append(svgEl('title',{},unit.label));group.append(outline);
        }
        const path = svgEl('polygon', {points:p.points.map(v=>v.join(',')).join(' '),class:merged?'sp-hit':`sp-panel ${e?.status || 'planned'} ${active ? 'selected' : ''} ${related?'corner-peer':''}`, 'data-key':p.key,opacity:editing&&!active&&!related?+q('[data-neighbour-opacity]').value/100:1});
        path.append(svgEl('title',{},`${p.label} · ${num(p.width_m,' m')}`)); group.append(path);
        if (i === 1) {
          const g = geometry(p); let angle = g.angle;
          if (angle > 90) angle -= 180; if (angle < -90) angle += 180;
          const scale = Math.max(box[2]/Math.max(250,q('[data-clean-svg]').clientWidth),box[3]/q('[data-clean-svg]').clientHeight);
          const font = Math.max(9,11*scale);
          const label = svgEl('text',{x:g.cx,y:g.cy,class:'sp-panel-label',transform:`rotate(${angle} ${g.cx} ${g.cy})`,'font-size':font});
          const anchor=corner?[...unit.members].sort((a,b)=>Math.abs(Math.sin(geometry(a).angle*Math.PI/180))-Math.abs(Math.sin(geometry(b).angle*Math.PI/180)))[0]:p;
          if(p===anchor)label.append(svgEl('tspan',{x:g.cx,dy:-font*.55,'data-unit-label':''},unit.label));
          label.append(svgEl('tspan',{x:g.cx,dy:p===anchor?font*1.1:0,'font-size':font*.9},`${corner?p.label.slice(-1).toUpperCase()+' · ':''}${num(p.width_m,' m')}${e?.sonic ? ' · S' : ''}${e?.inclinometer ? ' · I' : ''}`));group.append(label);
        }
        if (active && editing) {
          const visualScale=Math.max(box[2]/Math.max(1,group.ownerSVGElement.clientWidth),box[3]/Math.max(1,group.ownerSVGElement.clientHeight));
          if(widthLocked()||directionLocked()){
            Object.entries({start:[0,3],end:[1,2],top:[0,1],bottom:[3,2]}).forEach(([edge,ids])=>{
              const [a,b]=ids.map(j=>p.points[j]);
              if(!merged&&edge===q('[data-edge]').value)group.append(svgEl('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'sp-edit-edge'}));
              group.append(svgEl('circle',{cx:(a[0]+b[0])/2,cy:(a[1]+b[1])/2,r:7*visualScale,class:'sp-handle sp-edge-handle','data-key':p.key,'data-edge-handle':edge}));
            });
          }else p.points.forEach((v,j)=>{group.append(svgEl('circle',{cx:v[0],cy:v[1],r:7*visualScale,class:'sp-handle','data-key':p.key,'data-corner':j}));});
        }
      });
      drawn.add(unit);
    });
    q('[data-counter]').textContent = `${displayUnits.length} ${displayUnits.length===1?t('pannello','panneau'):t('pannelli','panneaux')}`;
  }
  function choose(key) { selected = key; renderDetail(); renderMaps(); q('[data-select]').value = unitFor(panel())?.members[0].key || ''; }
  function renderDetail() {
    const p = panel(), e = element(p);
    const snapPicker=q('[data-snap-target]'),oldTarget=snapPicker.value;snapPicker.replaceChildren();
    plan.layout.panels.filter(v=>v.key!==selected).sort((a,b)=>a.label.localeCompare(b.label,fr?'fr':'it',{numeric:true})).forEach(v=>snapPicker.add(new Option(v.label,v.key)));
    if([...snapPicker.options].some(o=>o.value===oldTarget))snapPicker.value=oldTarget;
    q('[data-undo-snap]').hidden=!snapUndo;
    form.hidden = !editing || !p;
    q('[data-geometry-tools]').hidden=!editing||!p;
    q('[data-undo-edit]').disabled=busy||!editUndo.length;
    q('[data-undo-removal]').hidden=!editing||!!p||!editUndo.length;
    form.elements.shape_length.disabled=busy||widthLocked();form.elements.angle.disabled=busy||directionLocked();
    q('[data-edit-hint]').textContent=widthLocked()?t('Larghezza bloccata nei trascinamenti. Le testate si spostano insieme.','Largeur verrouillée pendant le déplacement. Les extrémités se déplacent ensemble.'):t('Sposta un lato intero: i due lati collegati si allungano insieme.','Déplacez un côté entier : les deux côtés adjacents s’allongent ensemble.');
    const pair=peers(p),corner=pair.length===2&&!!p?.corner_group;
    q('[data-arm-choice]').hidden=!corner||!editing;
    q('[data-label-caption]').textContent=corner?t('Sigla braccio','Repère de la branche'):tr('Sigla');
    q('[data-width-caption]').textContent=corner?t('Larghezza braccio (m)','Largeur de la branche (m)'):tr('Larghezza (m)');
    const arms=q('[data-arm]');arms.replaceChildren();pair.forEach(v=>arms.add(new Option(v.label,v.key)));arms.value=p?.key||'';
    q('[data-corner-info]').hidden=!corner;q('[data-corner-tools]').hidden=!corner;
    if(corner){q('[data-corner-label]').textContent=p.label.replace(/[ab]$/i,'')+' A/B';q('[data-corner-widths]').textContent=pair.map(v=>`${v.label}: ${num(v.width_m,' m')}`).join(' + ');form.elements.corner_net_confirmed.checked=pair.every(v=>v.corner_net_confirmed);}
    q('[data-label]').textContent = unitFor(p)?.label || tr("Seleziona un pannello");
    q('[data-warnings]').textContent = !p ? '' : editing ? [...((p.warnings || []).map(tr)),offScale(p)?tr("Sagoma fuori scala: applica la larghezza alla scala comune."):'',extent(p)?tr("Possibile sbordo rispetto alla sagoma riconosciuta o al foglio. Controlla sul PDF e conferma."):''].filter(Boolean).join(' · ') : '';
    if (p) {
      form.elements.label.value = p.label; form.elements.width_m.value = p.width_m ?? ''; form.elements.element.value = p.element ?? ''; form.elements.reviewed.checked = p.reviewed; form.elements.extent_confirmed.checked=!!p.extent_confirmed; q('[data-extent]').hidden=!extent(p); q('[data-scale-info]').textContent=commonScale()?t(`Scala comune: ${num(commonScale())} punti del foglio per metro`,`Échelle commune : ${num(commonScale())} points de la feuille par mètre`):tr("Scala da calibrare");
      const g = geometry(p); Object.entries({cx:g.cx,cy:g.cy,shape_length:g.len,shape_depth:g.depth,angle:g.angle}).forEach(([k,v])=>form.elements[k].value=+v.toFixed(2));
    }
    const dl = q('[data-details]'); dl.replaceChildren();
    const rows = p ? [[corner?t('Sviluppo angolo','Développé de l’angle'):tr("Larghezza pianta"),num(corner?pair.reduce((sum,v)=>sum+(v.width_m||0),0):p.width_m,' m')],[tr("Collegamento"), e ? `${e.label} · #${e.number}` : tr("Da associare")],[tr("Stato"), !e ? tr("Non collegato") : {cast:tr("Getto registrato"),fiche:tr("Fiche presente"),planned:tr("Da eseguire")}[e.status]],['Coupe', e?.coupe || '—'],[tr("Armatura"),e?.armatura || '—'],[tr("Profondità prevista"),num(e?.planned_depth_m,' m')],[tr("Profondità effettiva"),num(e?.depth_m,' m')],[tr("Calcestruzzo gettato"),num(e?.concrete_m3,' m³')],[tr("Data getto"),e?.cast_date || '—'],[tr("Controlli previsti"),[e?.sonic?tr("Sonico"):'',e?.inclinometer?tr("Inclinometro"):''].filter(Boolean).join(' + ') || '—']] : [];
    rows.forEach(([k,v])=>{const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;row.append(dt,dd);dl.append(row);});
    const action = q('[data-fiche]'), target = e?.fiche_url || (!editing && e?.create_url);
    action.hidden = !target; if (target) action.href = target;
    action.textContent = e?.fiche_url ? tr("Apri fiche") : tr("Crea fiche");
  }
  function renderFooter() {
    if (!plan) return;
    const display=units(),pending=display.filter(u=>u.members.some(p=>!p.reviewed||!p.width_m||offScale(p)||(extent(p)&&!p.extent_confirmed)||(p.corner_group&&!p.corner_net_confirmed))).length,unlinked=display.filter(u=>u.members.some(p=>!p.element)).length;
    q('[data-pending]').textContent = `${pending} ${t('da verificare','à vérifier')} · ${unlinked} ${t('pannelli da creare alla convalida','panneaux à créer à la validation')}${dirty ? t(' · Modifiche non salvate',' · Modifications non enregistrées') : ''}`;
    q('[data-state]').textContent = editing ? tr("Bozza da convalidare") : tr("Disegno convalidato");
  }
  function render() {
    root.dataset.transparent=editing&&q('[data-transparent]').checked;
    root.dataset.original = showOriginal; q('[data-original]').hidden = !showOriginal; q('[data-original-toggle]').setAttribute('aria-pressed',showOriginal);
    q('[data-edit]').hidden = !data.can_edit || editing; q('[data-review-all-top]').hidden = q('[data-add]').hidden = !editing; q('[data-save-section]').hidden = !editing;
    q('[data-find-corners]').hidden=!editing;
    q('[data-replace]').hidden=!data.can_edit;q('[data-remove-draft]').hidden=!plan.can_remove;
    const picker = q('[data-select]'); picker.replaceChildren();
    units().forEach((u,i)=>picker.add(new Option(`${u.label} · ${t('zona','zone')} ${i+1}${u.members.every(p=>p.reviewed)?'':t(' · da verificare',' · à vérifier')}`,u.members[0].key)));
    picker.value = unitFor(panel())?.members[0].key || ''; renderDetail(); renderMaps(); renderFooter();
  }
  q('[data-select]').onchange = e => choose(e.target.value);
  q('[data-arm]').onchange=e=>choose(e.target.value);
  q('[data-version]').onchange = async e => { const id=+e.target.value;if (await guard()) load(id); else e.target.value = plan.id; };
  q('[data-edit]').onclick = async () => { if (await guard()) load(plan.id,true); };
  q('[data-original-toggle]').onclick = () => { showOriginal=!showOriginal; render(); };
  q('[data-fit]').onclick = () => { fit(); renderMaps(); };
  q('[data-zoom]').onclick = () => { const p=panel(); if(!p)return;const pts=peers(p).flatMap(v=>v.points),xs=pts.map(v=>v[0]),ys=pts.map(v=>v[1]),x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;box=[x-25,y-25,w+50,h+50];renderMaps(); };
  form.addEventListener('submit',e=>e.preventDefault());
  // Keep typed values before another control redraws the inspector (also mobile).
  root.addEventListener('input',e=>{
    if(e.target.form!==form)return;
    const p=panel();if(!editing||!p)return;
    if(e.target.name==='label')p.label=e.target.value;
    else if(e.target.name==='width_m')p.width_m=e.target.value&&e.target.validity.valid?+e.target.value:null;
    else return;
    invalidate(p);form.elements.reviewed.checked=false;markDirty();renderMaps();
  });
  root.addEventListener('change',e=>{
    if(e.target.form!==form)return;
    const p=panel(); if (!editing||!p) return;
    const input=e.target,name=input.name;
    if (name==='label') p.label=input.value.trim() || p.label;
    else if(name==='width_m') { if(input.value && (!input.validity.valid||!Number.isFinite(+input.value))){message(tr("Larghezza non valida."),true);return;}p.width_m=input.value ? +input.value : null; }
    else if(name==='element') {const value=input.value?+input.value:null;if(value&&plan.layout.panels.some(v=>v.key!==p.key&&v.element===value)){message(tr("Questo elemento è già associato a un’altra zona."),true);input.value=p.element||'';return;}p.element=value;}
    else if(name==='reviewed') p.reviewed=input.checked;
    else if(name==='extent_confirmed') p.extent_confirmed=input.checked;
    else if(name==='corner_net_confirmed') peers(p).forEach(v=>v.corner_net_confirmed=input.checked);
    else if(name==='anchor') return;
    else {
      const v=n=>+form.elements[n].value;
      const g={cx:v('cx'),cy:v('cy'),len:v('shape_length'),depth:v('shape_depth'),angle:v('angle')};
      if(widthLocked())g.len=geometry(p).len;if(directionLocked())g.angle=geometry(p).angle;
      checkpoint();
      if (!(g.len>1&&g.depth>1)||!updatePoints(p,rectangle(g))){message(tr("Dimensioni non valide o sagoma fuori dal foglio."),true);renderDetail();return;}
      if(!widthLocked()&&commonScale())p.width_m=g.len/commonScale();
    }
    if(!['reviewed','extent_confirmed','corner_net_confirmed'].includes(name))invalidate(p);markDirty();render();
  });
  q('[data-scale]').onclick = () => {const p=panel();checkpoint();if(!p||!resize(p,form.elements.anchor.value)){message(tr("Imposta una larghezza in metri e calibra la scala su un pannello noto."),true);return;}render();};
  q('[data-calibrate]').onclick=()=>{const p=panel();if(!p?.width_m){message(tr("Inserisci la larghezza reale in metri del pannello scelto."),true);return;}if(!confirm(t(`Usare la sagoma di ${p.label} (${num(p.width_m,' m')}) come riferimento per tutta la pianta?`,`Utiliser la forme de ${p.label} (${num(p.width_m,' m')}) comme référence pour tout le plan ?`)))return;plan.layout.scale_ppm=geometry(p).len/p.width_m;plan.layout.panels.forEach(v=>{v.reviewed=false;v.extent_confirmed=false;});markDirty();render();};
  q('[data-scale-all]').onclick=()=>{if(!commonScale()){message(tr("Calibra prima la scala su un pannello di larghezza nota."),true);return;}if(!confirm(tr("Proporzionare tutte le sagome alle larghezze in metri, mantenendo i loro centri? Controlla poi gli estremi sul PDF.")))return;plan.layout.scale_ppm=commonScale();plan.layout.panels.forEach(p=>resize(p));markDirty();fit();render();};
  q('[data-remove]').onclick = async () => {const p=panel(),unit=unitFor(p);if(!p||!await ask(t(`Rimuovere ${unit.label}?`,`Retirer ${unit.label} ?`),t('Viene rimossa solo la sagoma dalla bozza. Le fiche restano nel gestionale. Puoi usare Annulla modifica prima di salvare.','Seule la forme du brouillon sera retirée. Les fiches sont conservées. Vous pouvez annuler la modification avant d’enregistrer.'),t('Rimuovi pannello','Retirer le panneau')))return;checkpoint();const keys=new Set(unit.members.map(v=>v.key));plan.layout.panels=plan.layout.panels.filter(v=>!keys.has(v.key));selected=plan.layout.panels[0]?.key;markDirty();render();};
  q('[data-add]').onclick = () => {addMode=!addMode;message(addMode?tr("Trascina sul disegno per creare una sagoma rettangolare."):tr("Inserimento annullato."));q('[data-add]').textContent=addMode?tr("Annulla inserimento"):tr("Aggiungi pannello");};
  function coordinate(svg,event) {const pt=svg.createSVGPoint();pt.x=event.clientX;pt.y=event.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());return [p.x,p.y];}
  all('.sp-board svg').forEach(svg=>{
    svg.addEventListener('pointerdown',event=>{
      if(event.button!==0||busy)return;
      const key=event.target.dataset.key,corner=event.target.dataset.corner,edge=event.target.dataset.edgeHandle;
      if(key)choose(key);
      if(!editing||(!addMode&&!key))return;
      const start=coordinate(svg,event);svg.setPointerCapture(event.pointerId);
      if(edge)q('[data-edge]').value=edge;
      checkpoint();drag={svg,id:event.pointerId,start,corner:corner===undefined?null:+corner,edge,key:selected,points:panel()?.points.map(v=>[...v]),pair:peers(panel()).map(v=>({key:v.key,points:v.points.map(p=>[...p])})),add:addMode,moved:false};event.preventDefault();
    });
    svg.addEventListener('pointermove',event=>{
      if(!drag||drag.svg!==svg||drag.id!==event.pointerId)return;
      const now=coordinate(svg,event),dx=now[0]-drag.start[0],dy=now[1]-drag.start[1];
      if(Math.hypot(dx,dy)<1)return;drag.moved=true;
      if(drag.add){let ghost=svg.querySelector('.sp-ghost');if(!ghost){ghost=svgEl('rect',{class:'sp-ghost',fill:'#d5224730',stroke:'#d52247','pointer-events':'none'});svg.append(ghost);}Object.entries({x:Math.min(now[0],drag.start[0]),y:Math.min(now[1],drag.start[1]),width:Math.abs(dx),height:Math.abs(dy)}).forEach(([k,v])=>ghost.setAttribute(k,v));return;}
      const p=panel();if(!p)return;
      let pts;
      if(drag.edge){const a=geometry({points:drag.points}).angle*Math.PI/180,delta=['start','end'].includes(drag.edge)?dx*Math.cos(a)+dy*Math.sin(a):-dx*Math.sin(a)+dy*Math.cos(a);pts=window.PlanGeometry.moveEdge(drag.points,drag.edge,delta,widthLocked());}
      else pts=drag.points.map((v,i)=>drag.corner===null||drag.corner===i?[v[0]+dx,v[1]+dy]:[...v]);
      if(!drag.edge&&drag.corner===null){
        const moved=drag.pair.map(v=>({p:plan.layout.panels.find(x=>x.key===v.key),points:v.points.map(x=>[x[0]+dx,x[1]+dy])}));
        if(!moved.every(v=>inBounds(v.points)))return;
        moved.filter(v=>v.p.key!==p.key).forEach(v=>updatePoints(v.p,v.points));
      }
      if(updatePoints(p,pts)){if(!widthLocked()&&commonScale())p.width_m=geometry(p).len/commonScale();renderMaps();renderDetail();}
    });
    const finish=event=>{
      if(!drag||drag.svg!==svg||drag.id!==event.pointerId)return;
      if(drag.add&&event.type!=='pointercancel'){
        const end=coordinate(svg,event),x=Math.min(end[0],drag.start[0]),y=Math.min(end[1],drag.start[1]),w=Math.abs(end[0]-drag.start[0]),h=Math.abs(end[1]-drag.start[1]);
        const pts=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
        if(w>3&&h>3&&inBounds(pts)){const p={key:crypto.randomUUID().replaceAll('-',''),label:`P${plan.layout.panels.length+1}`,points:pts,width_m:null,element:null,reviewed:false,warnings:[tr("Pannello inserito manualmente")]};plan.layout.panels.push(p);selected=p.key;markDirty();}
        addMode=false;q('[data-add]').textContent=tr("Aggiungi pannello");
      }
      svg.querySelector('.sp-ghost')?.remove();drag=null;render();
    };
    svg.addEventListener('pointerup',finish);svg.addEventListener('pointercancel',finish);
  });
  q('[data-snap]').onclick=()=>{
    const p=panel(),target=plan.layout.panels.find(v=>v.key===q('[data-snap-target]').value);
    if(!editing||!p||!target)return;
    const result=window.PlanGeometry.snap(p.points,target.points);
    if(!result){message(t('Non ci sono bordi paralleli da accostare. Regola la rotazione o gli angoli.','Aucun bord parallèle à raccorder. Ajustez la rotation ou les angles.'),true);return;}
    if(!confirm(t(`Accostare ${p.label} a ${target.label}? Il pannello verrà spostato senza cambiare le dimensioni.`,`Raccorder ${p.label} à ${target.label} ? Le panneau sera déplacé sans modifier ses dimensions.`)))return;
    checkpoint();snapUndo={key:p.key,points:p.points.map(v=>[...v]),reviewed:p.reviewed,extent_confirmed:p.extent_confirmed};
    if(!updatePoints(p,result.points)){snapUndo=null;message(t('Spostamento fuori dallo spazio di lavoro.','Déplacement hors de la zone de travail.'),true);return;}
    render();message(t('Bordi accostati. Controlla il risultato sul PDF.','Bords raccordés. Vérifiez le résultat sur le PDF.'));
  };
  q('[data-undo-snap]').onclick=()=>{
    if(!snapUndo)return;const p=plan.layout.panels.find(v=>v.key===snapUndo.key);
    if(p){Object.assign(p,snapUndo);markDirty();}snapUndo=null;render();
  };
  q('[data-lock-width]').onchange=q('[data-lock-direction]').onchange=q('[data-transparent]').onchange=()=>render();
  q('[data-neighbour-opacity]').oninput=()=>renderMaps();
  q('[data-edge]').onchange=()=>renderMaps();
  all('[data-nudge]').forEach(button=>button.onclick=()=>{
    const p=panel(),scale=commonScale();if(!p||!editing)return;
    if(!scale){message(t('Calibra prima la scala.','Calibrez d’abord l’échelle.'),true);return;}
    checkpoint();const pts=window.PlanGeometry.moveEdge(p.points,q('[data-edge]').value,+button.dataset.nudge*(+q('[data-step]').value)*scale,widthLocked());
    if(updatePoints(p,pts)){if(!widthLocked())p.width_m=geometry(p).len/scale;render();}
  });
  q('[data-undo-edit]').onclick=()=>{if(!editUndo.length)return;plan.layout=JSON.parse(editUndo.pop());if(!panel())selected=plan.layout.panels[0]?.key;snapUndo=null;markDirty();render();};
  q('[data-undo-removal]').onclick=()=>q('[data-undo-edit]').click();
  q('[data-find-corners]').onclick=()=>{
    const pairs=window.PlanGeometry.cornerPairs(plan.layout.panels);
    if(!pairs.length){message(t('Nessun nuovo angolo A/B vicino e univoco riconosciuto.','Aucun nouvel angle A/B voisin et non ambigu reconnu.'));return;}
    checkpoint();pairs.forEach(pair=>pair.forEach(p=>{p.corner_group=pair.map(v=>v.key).sort()[0];p.corner_net_confirmed=false;p.reviewed=false;}));
    markDirty();render();message(t(`${pairs.length} angoli proposti: controlla misure e raccordi sul PDF.`,`${pairs.length} angles proposés : vérifiez les cotes et raccords sur le PDF.`));
  };
  q('[data-join-corner]').onclick=()=>{
    const p=panel(),pair=peers(p);if(pair.length!==2)return;
    const target=pair.find(v=>v.key!==p.key),result=window.PlanGeometry.snap(p.points,target.points);
    if(!result){message(t('Controlla le direzioni dei due bracci prima di raccordarli.','Vérifiez les directions des deux branches avant de les raccorder.'),true);return;}
    checkpoint();if(updatePoints(p,result.points)){render();message(t('Angolo raccordato senza cambiare le larghezze. Verifica le quote nette sul PDF.','Angle raccordé sans modifier les largeurs. Vérifiez les cotes nettes sur le PDF.'));}
  };
  q('[data-split-corner]').onclick=()=>{
    const pair=peers(panel());if(pair.length!==2)return;
    if(!confirm(t('Separare i due bracci? Le sagome restano ferme. Una fiche già compilata non verrà cancellata.','Séparer les deux branches ? Les formes restent en place. Aucune fiche existante ne sera supprimée.')))return;
    checkpoint();pair.forEach(p=>{p.corner_group=null;p.corner_net_confirmed=false;p.reviewed=false;});markDirty();render();
  };
  q('[data-review-all-top]').onclick=()=>q('[data-review-all]').click();
  q('[data-review-all]').onclick=()=>{
    const valid=plan.layout.panels.filter(p=>p.label.trim()&&p.width_m&&!offScale(p));
    const extents=valid.filter(extent);
    const text=t('Confermare tutti i pannelli completi dopo il confronto con il PDF?','Confirmer tous les panneaux complets après vérification sur le PDF ?');
    if(!valid.length){message(t('Completa prima larghezze e scala.','Complétez d’abord les largeurs et l’échelle.'),true);return;}
    if(!confirm(text))return;
    let confirmExtents=false;
    if(extents.length)confirmExtents=confirm(t(`Sono previsti gli sbordi di questi pannelli? ${extents.map(p=>p.label).join(', ')}. Annulla per lasciarli da controllare.`,`Les débordements de ces panneaux sont-ils prévus ? ${extents.map(p=>p.label).join(', ')}. Annulez pour les laisser à vérifier.`));
    valid.forEach(p=>{p.reviewed=true;if(confirmExtents&&extent(p))p.extent_confirmed=true;});markDirty();render();
    message(t('Verifica completata. Premi Convalida disegno per salvare.','Vérification terminée. Cliquez sur Valider le plan pour enregistrer.'));
  };
  function lock(value) {busy=value;all('button').forEach(b=>b.disabled=value);all('input,select').forEach(b=>b.disabled=value);if(!value&&plan)renderDetail();}
  async function save(approve) {
    if(busy)return;
    if(approve&&plan.layout.panels.some(p=>p.corner_group&&!p.corner_net_confirmed)){
      const p=plan.layout.panels.find(p=>p.corner_group&&!p.corner_net_confirmed);choose(p.key);
      message(t('Verifica e conferma le larghezze nette dei bracci dell’angolo selezionato.','Vérifiez et confirmez les largeurs nettes des branches de l’angle sélectionné.'),true);return;
    }
    if(approve){const missing=plan.layout.panels.filter(p=>!p.reviewed||!p.width_m||offScale(p)||(extent(p)&&!p.extent_confirmed));if(!plan.layout.panels.length||missing.length){message(t(`Controlla scala, larghezze e conferme di sbordo dei pannelli (${missing.length} ancora da verificare).`,`Vérifiez l’échelle, les largeurs et les débordements (${missing.length} panneaux à vérifier).`),true);return;}
      const unlinked=units().filter(u=>u.members.some(p=>!p.element)).length;
      if(!confirm(t(`Convalidare il disegno? ${unlinked} pannelli nuovi potranno essere assegnati alle coupe.`,`Valider le plan ? ${unlinked} nouveaux panneaux pourront être affectés aux coupes.`)))return;
    }
    const id=plan.id;lock(true);
    try{await api(`${base}/${id}/${approve?'convalida':'bozza'}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:plan.revision,panels:plan.layout.panels,scale_ppm:commonScale(),confirm:approve})});dirty=false;await load(id,!approve);message(approve?tr("Disegno convalidato."):tr("Bozza salvata. Il disegno convalidato resta invariato."));}catch(e){message(e.message,true);}finally{lock(false);}
  }
  q('[data-save]').onclick=()=>save(false);q('[data-approve]').onclick=()=>save(true);
  function showUpload(replace=false){replacement=replace&&plan?.can_remove?{id:plan.id,revision:plan.revision}:null;const note=q('[data-replace-notice]');note.hidden=!replace;note.textContent=replacement?t('Il nuovo PDF sostituirà questa bozza solo dopo un’analisi riuscita. La bozza rimossa resterà recuperabile dall’amministratore.','Le nouveau PDF remplacera ce brouillon uniquement après une analyse réussie. L’administrateur pourra restaurer le brouillon retiré.'):t('Il disegno convalidato resta disponibile. Il nuovo PDF verrà caricato come versione in bozza.','Le plan validé reste disponible. Le nouveau PDF sera importé comme nouvelle version en brouillon.');q('[data-upload]').hidden=false;q('[data-upload]').scrollIntoView({behavior:'smooth',block:'center'});}
  q('[data-upload-toggle]')?.addEventListener('click',()=>showUpload());
  q('[data-replace]').onclick=()=>showUpload(true);
  q('[data-upload-cancel]')?.addEventListener('click',()=>{replacement=null;q('[data-upload]').hidden=true;});
  q('[data-remove-draft]').onclick=async()=>{
    if(busy||!plan?.can_remove)return;
    if(!await ask(t('Rimuovere questa bozza?','Retirer ce brouillon ?'),t('Il PDF e i pannelli di questa bozza verranno rimossi dalla pianta. Il cantiere resta invariato. Le modifiche non salvate saranno scartate; il PDF e l’ultima bozza salvata resteranno recuperabili dall’amministratore.','Le PDF et les panneaux de ce brouillon seront retirés du plan. Le chantier reste inchangé. Les modifications non enregistrées seront abandonnées ; l’administrateur pourra restaurer le PDF et le dernier brouillon enregistré.'),t('Rimuovi bozza','Retirer le brouillon')))return;
    lock(true);try{await api(`${base}/${plan.id}/rimuovi`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:plan.revision})});await load();message(t('Bozza rimossa. Puoi caricare un altro PDF nello stesso cantiere.','Brouillon retiré. Vous pouvez importer un autre PDF dans le même chantier.'));}catch(e){message(tr(e.message),true);}finally{lock(false);}
  };
  q('[data-upload]')?.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;const payload=new FormData(event.currentTarget);
    if(replacement){if(!await ask(t('Sostituire il PDF?','Remplacer le PDF ?'),t('La bozza corrente verrà rimossa solo se il nuovo PDF è valido. Le modifiche non salvate saranno scartate.','Le brouillon actuel sera retiré uniquement si le nouveau PDF est valide. Les modifications non enregistrées seront abandonnées.'),t('Sostituisci PDF','Remplacer le PDF')))return;payload.set('replace_id',replacement.id);payload.set('replace_revision',replacement.revision);}else if(!await guard())return;
    lock(true);message(tr("Analisi del PDF in corso…"));
    try{const uploaded=await api(base+'/importa',{method:'POST',body:payload});dirty=false;q('[data-upload]').hidden=true;q('[data-upload]').reset();await load(uploaded.id,true);}catch(e){message(tr(e.message),true);}finally{lock(false);}
  });
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  load();
})();
