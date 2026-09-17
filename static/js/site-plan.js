/* Original PDFs and confirmed layouts stay independent of editable proposals. */
(() => {
  'use strict';
  const root = document.getElementById('site-plan-app');
  if (!root) return;
  const q = s => root.querySelector(s), all = s => [...root.querySelectorAll(s)];
  const base = `/manager/cantieri/${root.dataset.site}/pianta`, ns = 'http://www.w3.org/2000/svg';
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
  function num(v, unit = '') { return v == null ? '—' : `${Number(v).toLocaleString('it-IT', {maximumFractionDigits: 2})}${unit}`; }
  function svgEl(tag, attrs = {}, text) { const n = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v)); if (text != null) n.textContent = text; return n; }
  async function api(url, options = {}) {
    const res = await fetch(url, {credentials: 'same-origin', ...options});
    if (!res.headers.get('content-type')?.includes('application/json')) throw new Error('Sessione scaduta: accedi di nuovo prima di salvare.');
    const payload = await res.json();
    if (!res.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Dati non validi. Controlla misure e campi.');
    return payload;
  }
  function guard() { return !dirty || confirm('Ci sono modifiche non salvate. Vuoi abbandonarle?'); }
  async function load(id, draft = false) {
    try {
      data = await api(base + '/data' + (id ? `?plan_id=${id}&draft=${draft}` : ''));
      plan = data.plan; editing = !!plan?.editing; dirty = false; addMode = false;
      const versions = q('[data-version]'); versions.replaceChildren();
      data.versions.forEach(v => versions.add(new Option(`#${v.id} · ${v.filename} · ${v.approved ? 'convalidata' : 'bozza'}${v.approved && v.has_draft ? ' + modifiche in bozza' : ''}`, v.id)));
      q('[data-empty]').hidden = !!plan; q('[data-workspace]').hidden = !plan;
      if (!plan) { message('Carica un PDF per preparare la pianta del cantiere.'); if (q('[data-upload]')) q('[data-upload]').hidden = false; return; }
      versions.value = plan.id; selected = plan.layout.panels[0]?.key; showOriginal = editing;
      q('[data-pdf]').href = plan.original_url; q('[data-page]').textContent = `Pagina ${plan.page_number}`;
      const image = q('[data-preview]'); image.setAttribute('href', plan.preview_url); image.setAttribute('width', plan.layout.width); image.setAttribute('height', plan.layout.height);
      const links = form.elements.element; links.replaceChildren(new Option('Crea pannello alla convalida', ''));
      data.elements.forEach(e => links.add(new Option(`${e.label} · elemento ${e.number}${e.fiche_id ? ' · fiche presente' : ''}`, e.number)));
      plan.layout.panels.forEach(p => {p.reference_points ||= p.points.map(v=>[...v]);});
      plan.layout.scale_ppm=commonScale();
      fit(); render();
      message(editing ? plan.layout.notice : 'Disegno convalidato. Avanzamento e dati provengono dalle fiches collegate.');
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
  function updatePoints(p, points) { if (!inBounds(points)) return false; p.points = points; p.reviewed = false; p.extent_confirmed = false; markDirty(); return true; }
  function renderMaps() {
    if (!plan) return;
    all('.sp-board svg').forEach(svg=>svg.setAttribute('viewBox', box.join(' ')));
    const groups = [q('[data-original-shapes]'),q('[data-clean-shapes]')]; groups.forEach(g=>g.replaceChildren());
    plan.layout.panels.forEach(p => {
      const e = element(p), active = p.key === selected;
      groups.forEach((group,i) => {
        const path = svgEl('polygon', {points:p.points.map(v=>v.join(',')).join(' '),class:`sp-panel ${e?.status || 'planned'} ${active ? 'selected' : ''}`, 'data-key':p.key});
        path.append(svgEl('title',{},`${p.label} · ${num(p.width_m,' m')}`)); group.append(path);
        if (i === 1) {
          const g = geometry(p); let angle = g.angle;
          if (angle > 90) angle -= 180; if (angle < -90) angle += 180;
          const scale = Math.max(box[2]/Math.max(250,q('[data-clean-svg]').clientWidth),box[3]/q('[data-clean-svg]').clientHeight);
          const font = Math.max(9,11*scale);
          const label = svgEl('text',{x:g.cx,y:g.cy,class:'sp-panel-label',transform:`rotate(${angle} ${g.cx} ${g.cy})`,'font-size':font});
          label.append(svgEl('tspan',{x:g.cx,dy:-font*.1},p.label));
          label.append(svgEl('tspan',{x:g.cx,dy:font*1.15,'font-size':font*.9},`${num(p.width_m,' m')}${e?.sonic ? ' · S' : ''}${e?.inclinometer ? ' · I' : ''}`));group.append(label);
        }
        if (active && editing) p.points.forEach((v,j)=>{group.append(svgEl('circle',{cx:v[0],cy:v[1],r:Math.max(4,box[2]/130),class:'sp-handle','data-key':p.key,'data-corner':j}));group.append(svgEl('text',{x:v[0],y:v[1]-5,'font-size':Math.max(7,box[2]/90),fill:'currentColor','pointer-events':'none'},j+1));});
      });
    });
    q('[data-counter]').textContent = `${plan.layout.panels.length} pannelli`;
  }
  function choose(key) { selected = key; renderDetail(); renderMaps(); q('[data-select]').value = key || ''; }
  function renderDetail() {
    const p = panel(), e = element(p); form.hidden = !editing || !p;
    q('[data-label]').textContent = p?.label || 'Seleziona un pannello';
    q('[data-warnings]').textContent = !p ? '' : editing ? [...(p.warnings || []),offScale(p)?'Sagoma fuori scala: applica la larghezza alla scala comune.':'',extent(p)?'Possibile sbordo rispetto alla sagoma riconosciuta o al foglio. Controlla sul PDF e conferma.':''].filter(Boolean).join(' · ') : '';
    if (p) {
      form.elements.label.value = p.label; form.elements.width_m.value = p.width_m ?? ''; form.elements.element.value = p.element ?? ''; form.elements.reviewed.checked = p.reviewed; form.elements.extent_confirmed.checked=!!p.extent_confirmed; q('[data-extent]').hidden=!extent(p); q('[data-scale-info]').textContent=commonScale()?`Scala comune: ${num(commonScale())} punti del foglio per metro`:'Scala da calibrare';
      const g = geometry(p); Object.entries({cx:g.cx,cy:g.cy,shape_length:g.len,shape_depth:g.depth,angle:g.angle}).forEach(([k,v])=>form.elements[k].value=+v.toFixed(2));
    }
    const dl = q('[data-details]'); dl.replaceChildren();
    const rows = p ? [['Larghezza pianta',num(p.width_m,' m')],['Collegamento', e ? `${e.label} · #${e.number}` : 'Da associare'],['Stato', !e ? 'Non collegato' : {cast:'Getto registrato',fiche:'Fiche presente',planned:'Da eseguire'}[e.status]],['Coupe', e?.coupe || '—'],['Armatura',e?.armatura || '—'],['Profondità prevista',num(e?.planned_depth_m,' m')],['Profondità effettiva',num(e?.depth_m,' m')],['Calcestruzzo gettato',num(e?.concrete_m3,' m³')],['Data getto',e?.cast_date || '—'],['Controlli previsti',[e?.sonic?'Sonico':'',e?.inclinometer?'Inclinometro':''].filter(Boolean).join(' + ') || '—']] : [];
    rows.forEach(([k,v])=>{const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;row.append(dt,dd);dl.append(row);});
    const action = q('[data-fiche]'), target = e?.fiche_url || (!editing && e?.create_url);
    action.hidden = !target; if (target) action.href = target;
    action.textContent = e?.fiche_url ? 'Apri fiche' : 'Crea fiche';
  }
  function renderFooter() {
    if (!plan) return;
    const pending = plan.layout.panels.filter(p=>!p.reviewed||!p.width_m||offScale(p)||(extent(p)&&!p.extent_confirmed)).length, unlinked = plan.layout.panels.filter(p=>!p.element).length;
    q('[data-pending]').textContent = `${pending} da verificare · ${unlinked} pannelli da creare alla convalida${dirty ? ' · Modifiche non salvate' : ''}`;
    q('[data-state]').textContent = editing ? 'Bozza da convalidare' : 'Disegno convalidato';
  }
  function render() {
    root.dataset.original = showOriginal; q('[data-original]').hidden = !showOriginal; q('[data-original-toggle]').setAttribute('aria-pressed',showOriginal);
    q('[data-edit]').hidden = !data.can_edit || editing; q('[data-add]').hidden = !editing; q('[data-save-section]').hidden = !editing;
    const picker = q('[data-select]'); picker.replaceChildren();
    plan.layout.panels.forEach((p,i)=>picker.add(new Option(`${p.label} · zona ${i+1}${p.reviewed?'':' · da verificare'}`,p.key)));
    picker.value = selected || ''; renderDetail(); renderMaps(); renderFooter();
  }
  q('[data-select]').onchange = e => choose(e.target.value);
  q('[data-version]').onchange = e => { if (guard()) load(+e.target.value); else e.target.value = plan.id; };
  q('[data-edit]').onclick = () => { if (guard()) load(plan.id,true); };
  q('[data-original-toggle]').onclick = () => { showOriginal=!showOriginal; render(); };
  q('[data-fit]').onclick = () => { fit(); renderMaps(); };
  q('[data-zoom]').onclick = () => { const p=panel(); if(!p)return;const g=geometry(p),size=Math.max(70,g.len*1.9);box=[g.cx-size/2,g.cy-size/2,size,size];renderMaps(); };
  form.addEventListener('submit',e=>e.preventDefault());
  // Keep typed values before another control redraws the inspector (also mobile).
  form.addEventListener('input',e=>{
    const p=panel();if(!editing||!p)return;
    if(e.target.name==='label')p.label=e.target.value;
    else if(e.target.name==='width_m')p.width_m=e.target.value&&e.target.validity.valid?+e.target.value:null;
    else return;
    p.reviewed=false;form.elements.reviewed.checked=false;markDirty();renderMaps();
  });
  form.addEventListener('change',e=>{
    const p=panel(); if (!editing||!p) return;
    const input=e.target,name=input.name;
    if (name==='label') p.label=input.value.trim() || p.label;
    else if(name==='width_m') { if(input.value && (!input.validity.valid||!Number.isFinite(+input.value))){message('Larghezza non valida.',true);return;}p.width_m=input.value ? +input.value : null; }
    else if(name==='element') {const value=input.value?+input.value:null;if(value&&plan.layout.panels.some(v=>v.key!==p.key&&v.element===value)){message('Questo elemento è già associato a un’altra zona.',true);input.value=p.element||'';return;}p.element=value;}
    else if(name==='reviewed') p.reviewed=input.checked;
    else if(name==='extent_confirmed') p.extent_confirmed=input.checked;
    else if(name==='anchor') return;
    else {
      const v=n=>+form.elements[n].value;
      const g={cx:v('cx'),cy:v('cy'),len:v('shape_length'),depth:v('shape_depth'),angle:v('angle')};
      if (!(g.len>1&&g.depth>1)||!updatePoints(p,rectangle(g))){message('Dimensioni non valide o sagoma fuori dal foglio.',true);renderDetail();return;}
    }
    if(!['reviewed','extent_confirmed'].includes(name))p.reviewed=false;markDirty();render();
  });
  q('[data-scale]').onclick = () => {const p=panel();if(!p||!resize(p,form.elements.anchor.value)){message('Imposta una larghezza in metri e calibra la scala su un pannello noto.',true);return;}render();};
  q('[data-calibrate]').onclick=()=>{const p=panel();if(!p?.width_m){message('Inserisci la larghezza reale in metri del pannello scelto.',true);return;}if(!confirm(`Usare la sagoma di ${p.label} (${num(p.width_m,' m')}) come riferimento per tutta la pianta?`))return;plan.layout.scale_ppm=geometry(p).len/p.width_m;plan.layout.panels.forEach(v=>{v.reviewed=false;v.extent_confirmed=false;});markDirty();render();};
  q('[data-scale-all]').onclick=()=>{if(!commonScale()){message('Calibra prima la scala su un pannello di larghezza nota.',true);return;}if(!confirm('Proporzionare tutte le sagome alle larghezze in metri, mantenendo i loro centri? Controlla poi gli estremi sul PDF.'))return;plan.layout.scale_ppm=commonScale();plan.layout.panels.forEach(p=>resize(p));markDirty();fit();render();};
  q('[data-remove]').onclick = () => {const p=panel();if(!p||!confirm(`Rimuovere ${p.label} dalla pianta? Le sue fiches restano nel gestionale.`))return;plan.layout.panels=plan.layout.panels.filter(v=>v.key!==p.key);selected=plan.layout.panels[0]?.key;markDirty();render();};
  q('[data-add]').onclick = () => {addMode=!addMode;message(addMode?'Trascina sul disegno per creare una sagoma rettangolare.':'Inserimento annullato.');q('[data-add]').textContent=addMode?'Annulla inserimento':'Aggiungi pannello';};
  function coordinate(svg,event) {const pt=svg.createSVGPoint();pt.x=event.clientX;pt.y=event.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());return [p.x,p.y];}
  all('.sp-board svg').forEach(svg=>{
    svg.addEventListener('pointerdown',event=>{
      if(event.button!==0||busy)return;
      const key=event.target.dataset.key,corner=event.target.dataset.corner;
      if(key)choose(key);
      if(!editing||(!addMode&&!key))return;
      const start=coordinate(svg,event);svg.setPointerCapture(event.pointerId);
      drag={svg,id:event.pointerId,start,corner:corner===undefined?null:+corner,key:selected,points:panel()?.points.map(v=>[...v]),add:addMode,moved:false};event.preventDefault();
    });
    svg.addEventListener('pointermove',event=>{
      if(!drag||drag.svg!==svg||drag.id!==event.pointerId)return;
      const now=coordinate(svg,event),dx=now[0]-drag.start[0],dy=now[1]-drag.start[1];
      if(Math.hypot(dx,dy)<1)return;drag.moved=true;
      if(drag.add){let ghost=svg.querySelector('.sp-ghost');if(!ghost){ghost=svgEl('rect',{class:'sp-ghost',fill:'#d5224730',stroke:'#d52247','pointer-events':'none'});svg.append(ghost);}Object.entries({x:Math.min(now[0],drag.start[0]),y:Math.min(now[1],drag.start[1]),width:Math.abs(dx),height:Math.abs(dy)}).forEach(([k,v])=>ghost.setAttribute(k,v));return;}
      const p=panel();if(!p)return;const pts=drag.points.map((v,i)=>drag.corner===null||drag.corner===i?[v[0]+dx,v[1]+dy]:[...v]);
      if(updatePoints(p,pts)){renderMaps();renderDetail();}
    });
    const finish=event=>{
      if(!drag||drag.svg!==svg||drag.id!==event.pointerId)return;
      if(drag.add&&event.type!=='pointercancel'){
        const end=coordinate(svg,event),x=Math.min(end[0],drag.start[0]),y=Math.min(end[1],drag.start[1]),w=Math.abs(end[0]-drag.start[0]),h=Math.abs(end[1]-drag.start[1]);
        const pts=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
        if(w>3&&h>3&&inBounds(pts)){const p={key:crypto.randomUUID().replaceAll('-',''),label:`P${plan.layout.panels.length+1}`,points:pts,width_m:null,element:null,reviewed:false,warnings:['Pannello inserito manualmente']};plan.layout.panels.push(p);selected=p.key;markDirty();}
        addMode=false;q('[data-add]').textContent='Aggiungi pannello';
      }
      svg.querySelector('.sp-ghost')?.remove();drag=null;render();
    };
    svg.addEventListener('pointerup',finish);svg.addEventListener('pointercancel',finish);
  });
  q('[data-review-all]').onclick = () => {if(!confirm('Hai controllato sigle, larghezze e sagome di tutti i pannelli rispetto al PDF originale?'))return;plan.layout.panels.forEach(p=>{if(p.width_m)p.reviewed=true;});markDirty();render();};
  function lock(value) {busy=value;all('button').forEach(b=>b.disabled=value);all('input,select').forEach(b=>b.disabled=value);}
  async function save(approve) {
    if(busy)return;
    if(approve){const missing=plan.layout.panels.filter(p=>!p.reviewed||!p.width_m||offScale(p)||(extent(p)&&!p.extent_confirmed));if(!plan.layout.panels.length||missing.length){message(`Controlla scala, larghezze e conferme di sbordo dei pannelli (${missing.length} ancora da verificare).`,true);return;}
      const unlinked=plan.layout.panels.filter(p=>!p.element).length;
      if(!confirm(`Convalidare il disegno?${unlinked?` ${unlinked} pannelli verranno creati nel progetto con queste sigle. Potrai poi assegnarli alle coupe.`:''}`))return;
    }
    const id=plan.id;lock(true);
    try{await api(`${base}/${id}/${approve?'convalida':'bozza'}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:plan.revision,panels:plan.layout.panels,scale_ppm:commonScale(),confirm:approve})});dirty=false;await load(id,!approve);message(approve?'Disegno convalidato.':'Bozza salvata. Il disegno convalidato resta invariato.');}catch(e){message(e.message,true);}finally{lock(false);}
  }
  q('[data-save]').onclick=()=>save(false);q('[data-approve]').onclick=()=>save(true);
  q('[data-upload-toggle]')?.addEventListener('click',()=>{q('[data-upload]').hidden=!q('[data-upload]').hidden;});
  q('[data-upload]')?.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!guard())return;const payload=new FormData(event.currentTarget);lock(true);message('Analisi del PDF in corso…');
    try{const uploaded=await api(base+'/importa',{method:'POST',body:payload});dirty=false;q('[data-upload]').hidden=true;await load(uploaded.id,true);}catch(e){message(e.message,true);}finally{lock(false);}
  });
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  load();
})();
