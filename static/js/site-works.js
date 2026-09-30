/* General works: independent of excavation/pour geometry and fiche state. */
(()=>{
  'use strict';
  const root=document.querySelector('#works-app');if(!root)return;
  const $=id=>document.getElementById(id), url=`/manager/cantieri/${root.dataset.site}/avanzamento`;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=v=>JSON.parse(JSON.stringify(v)), uid=()=>crypto.randomUUID().replaceAll('-','');
  const num=v=>v==null?'—':Number(v).toLocaleString('it-IT',{maximumFractionDigits:2});
  const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  const center=p=>p.points.reduce((v,q)=>[v[0]+q[0]/p.points.length,v[1]+q[1]/p.points.length],[0,0]);
  const labels={planned:'Da eseguire',installed:'Posato',removed:'Rimosso',completed:'Realizzato',pumping:'Pompa attiva',stopped:'Pompa ferma'};
  let data,levelId,selection=null,mode=null,view=null,busy=false,formSubmit=null;
  let reader=null,sourceAnchors=[],targetAnchors=[],crop=null,drag=null,proposalIndex=0,reposition=false;
  const panels=()=>data.reference?.layout.panels||[];
  const panel=key=>panels().find(p=>p.key===key);
  const level=()=>data.works.levels.find(l=>l.id===levelId);
  const strut=()=>selection?.kind==='strut'?level()?.struts.find(s=>s.id===selection.id):null;
  function message(text){$('wm-message').textContent=text;}
  async function api(path,options={}){
    const response=await fetch(url+path,{credentials:'same-origin',...options});
    const result=await response.json().catch(()=>({detail:'Risposta non leggibile. Riprova.'}));
    if(!response.ok){const detail=Array.isArray(result.detail)?result.detail.map(x=>x.msg).join(' · '):result.detail;throw Error(detail||'Operazione non riuscita.');}
    return result;
  }
  async function load(){data=await api('/data');levelId=data.works.levels.some(l=>l.id===levelId)?levelId:data.works.levels[0]?.id;render();}
  function body(works){return {revision:data.revision,plan_id:data.reference.plan_id,plan_revision:data.reference.revision,works};}
  async function save(works,removed=[]){
    if(busy)throw Error('Attendi il salvataggio in corso.');busy=true;
    try{const result=await api('/data',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body(works),confirm_remove:removed})});data.works=result.works;data.revision=result.revision;render();message('Modifiche salvate.');}
    finally{busy=false;}
  }
  async function action(fn){try{await fn();}catch(e){message(e.message);}}
  function bbox(points,pad=.07){
    if(!points.length)return [0,0,100,100];
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);let x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;
    const margin=Math.max(w,h,1)*pad;return [x-margin,y-margin,Math.max(w+2*margin,10),Math.max(h+2*margin,10)];
  }
  function fullBox(){return bbox(panels().flatMap(p=>p.points),.12);}
  const pts=points=>points.map(p=>p.join(',')).join(' ');
  function phase(label,done,total,caption){const percent=total?Math.round(done/total*100):0;return `<div class="wm-phase"><span>${esc(label)}</span><strong>${percent}%</strong><small>${esc(caption)}</small><progress max="100" value="${percent}"></progress></div>`;}
  function phases(){
    const all=data.works.levels.flatMap(l=>l.struts),w=data.works.wells,nums=new Set(panels().map(p=>p.element).filter(Boolean));
    const cast=data.elements.filter(e=>nums.has(e.number)&&e.status==='cast').length;
    const sum=data.summary,placed=all.filter(s=>s.status==='installed').length,removed=all.filter(s=>s.status==='removed').length;
    $('wm-phases').innerHTML=phase('Installazione',sum.installazione_cantiere.done,100,`${num(sum.installazione_cantiere.done)}% registrato`)+
      phase('Muretti guida',sum.cordoli.done,sum.cordoli.total,`${num(sum.cordoli.done)} / ${num(sum.cordoli.total)} m`)+
      phase('Paratie',cast,nums.size,`${cast} / ${nums.size} gettate · dalle fiches`)+
      phase('Puntoni',placed,all.length,`${placed} / ${all.length} in opera · ${removed} rimossi`)+
      phase('Pozzi',w.filter(x=>x.status!=='planned').length,w.length,`${w.length} pozzi · ${w.filter(x=>x.status==='pumping').length} pompe attive`)+
      phase('Rabotage',data.works.rabotage.length,nums.size,`${data.works.rabotage.length} / ${nums.size} pannelli`);
  }
  function render(){
    phases();$('wm-empty').hidden=!!data.reference;$('wm-workspace').hidden=!data.reference;
    message(data.reference_changed?'La pianta delle paratie è cambiata. Questa mappa conserva la versione di riferimento per non spostare le opere già registrate. Controlla l’allineamento prima di nuove lavorazioni.':'');
    if(!data.reference)return;
    $('wm-level').innerHTML=data.works.levels.length?data.works.levels.map(l=>`<option value="${esc(l.id)}">${esc(l.name)}${l.axis_ngf!=null?' · asse '+num(l.axis_ngf)+' NGF':''}</option>`).join(''):'<option value="">Nessun livello configurato</option>';
    $('wm-level').value=levelId||'';
    const l=level();$('wm-level-count').textContent=l?`${l.struts.filter(s=>s.status==='installed').length} / ${l.struts.length} posati in questo livello`:'';
    for(const id of ['wm-edit-level','wm-add-strut','wm-read'])if($(id))$(id).disabled=!l;
    $('wm-sources').innerHTML=data.sources.map(s=>`<p><a href="${url}/pdf/${s.id}/originale" target="_blank" rel="noopener">${esc(s.filename)}</a> · pagina ${s.page} ${data.can_edit?`<button class="btn btn-secondary" data-reread="${s.id}">Riapri lettura</button>`:''}</p>`).join('')||'<p>Nessun PDF puntoni caricato.</p>';
    $('wm-legacy').innerHTML=data.legacy_levels.length?'<h3>Riepiloghi manuali precedenti</h3><p>Restano conservati. La mappa conta solo i singoli elementi qui confermati.</p>'+data.legacy_levels.map(l=>`<p>${esc(l.name)} · ${esc(l.quota||'Quota non indicata')} · ${l.done} / ${l.total}</p>`).join(''):'';
    draw();detail();
  }
  function panelShapes(selected=[],rab=false,font=10,labelKeys=null){
    const occupied=[],bounds=fullBox(),middle=[bounds[0]+bounds[2]/2,bounds[1]+bounds[3]/2];
    function labelPosition(p,c){
      const poly=p.points,edges=poly.map((a,i)=>({a,b:poly[(i+1)%poly.length],len:dist(a,poly[(i+1)%poly.length])})).sort((a,b)=>b.len-a.len);
      const e=edges[0],dx=(e.b[0]-e.a[0])/e.len,dy=(e.b[1]-e.a[1])/e.len;let nx=-dy,ny=dx;
      if((c[0]-middle[0])*nx+(c[1]-middle[1])*ny<0){nx=-nx;ny=-ny;}
      const width=(p.label.length*.61+1)*font,height=font*1.4;
      for(const offset of [1.8,3.6,5.4,0])for(const along of [0,2,-2,4,-4]){
        const x=c[0]+nx*offset*font+dx*along*font,y=c[1]+ny*offset*font+dy*along*font,b=[x-width/2,y-height/2,width,height];
        if(occupied.some(v=>b[0]<v[0]+v[2]&&b[0]+b[2]>v[0]&&b[1]<v[1]+v[3]&&b[1]+b[3]>v[1]))continue;
        occupied.push(b);return [x,y];
      }
      return c;
    }
    return panels().map(p=>{
      const c=center(p),active=selected.includes(p.key),treated=rab&&data.works.rabotage.includes(p.element);
      const at=labelPosition(p,c),show=labelKeys===null||labelKeys.includes(p.key);
      return `<g data-kind="panel" data-id="${esc(p.key)}" data-panel="${esc(p.key)}" tabindex="0" role="button" aria-label="Pannello ${esc(p.label)}"><polygon points="${pts(p.points)}" fill="${active?'#74384f':treated?'#9060bd':'#37586a'}" stroke="${active?'#ff557a':'#b4cbd8'}" stroke-width="${active?2:1}" vector-effect="non-scaling-stroke"/>${show?`<line x1="${c[0]}" y1="${c[1]}" x2="${at[0]}" y2="${at[1]}" stroke="#809cad" stroke-width=".5" vector-effect="non-scaling-stroke" pointer-events="none"/><text x="${at[0]}" y="${at[1]}" text-anchor="middle" dominant-baseline="middle" font-size="${font}">${esc(p.label)}</text>`:''}</g>`;
    }).join('');
  }
  function tubePolygon(t,width){
    const dx=t.b[0]-t.a[0],dy=t.b[1]-t.a[1],length=Math.hypot(dx,dy),u=[dx/length,dy/length],n=[-u[1],u[0]];
    const cross=(a,b)=>a[0]*b[1]-a[1]*b[0],sub=(a,b)=>[a[0]-b[0],a[1]-b[1]];
    function endPoint(end,sign){
      const origin=t[end],poly=panel(t['panel_'+end]).points,offset=[origin[0]+n[0]*width*.5*sign,origin[1]+n[1]*width*.5*sign];
      const edges=poly.map((a,i)=>{const b=poly[(i+1)%poly.length],v=sub(b,a),len=Math.hypot(...v),projection=((origin[0]-a[0])*v[0]+(origin[1]-a[1])*v[1])/(len*len);return {a,v,d:Math.abs(cross(sub(origin,a),v))/len+(projection<-.001||projection>1.001?1e9:0)};}).sort((a,b)=>a.d-b.d);
      const edge=edges[0],den=cross(u,edge.v);if(Math.abs(den)<1e-8)return offset;
      const distance=cross(sub(edge.a,offset),edge.v)/den;return [offset[0]+distance*u[0],offset[1]+distance*u[1]];
    }
    return [endPoint('a',1),endPoint('b',1),endPoint('b',-1),endPoint('a',-1)];
  }
  function draw(){
    const box=view||fullBox(),scale=Math.min($('wm-map').clientWidth/box[2],$('wm-map').clientHeight/box[3]),font=(window.innerWidth<600?10:12)/Math.max(scale,.01),s=strut();
    $('wm-zoom-a').disabled=!s;$('wm-zoom-b').disabled=!s;
    $('wm-map').setAttribute('viewBox',box.join(' '));
    const supports=s?[s.panel_a,s.panel_b]:selection?.kind==='panel'?[selection.id]:[];
    // Subtract the wall faces from thick tubes, preserving oblique bearing edges.
    let html=`<defs><mask id="wm-interior" maskUnits="userSpaceOnUse" x="${box[0]}" y="${box[1]}" width="${box[2]}" height="${box[3]}"><rect x="${box[0]}" y="${box[1]}" width="${box[2]}" height="${box[3]}" fill="white"/>${panels().map(p=>`<polygon points="${pts(p.points)}" fill="black"/>`).join('')}</mask></defs>`;
    const compact=window.innerWidth<600&&!view;
    html+=panelShapes(supports,$('wm-rabotage').checked,font*.95,compact?supports:null);
    if($('wm-struts').checked){
      for(const t of level()?.struts||[]){
        const active=t.id===s?.id,color=t.status==='installed'?'#50c6a4':t.status==='removed'?'#8197a3':'#69b8ea';
        const width=t.diameter_mm&&data.reference.layout.scale_ppm?t.diameter_mm/1000*data.reference.layout.scale_ppm:font*.42;
        const middle=[(t.a[0]+t.b[0])/2,(t.a[1]+t.b[1])/2];
        const tube=t.status==='removed'?`<line x1="${t.a[0]}" y1="${t.a[1]}" x2="${t.b[0]}" y2="${t.b[1]}" stroke="${color}" stroke-width="${Math.max(width,font*.2)}" stroke-dasharray="${font*.8} ${font*.45}"/>`:`<polygon points="${pts(tubePolygon(t,Math.max(width,font*.2)))}" fill="${active?'#ff5275':color}"/><polygon points="${pts(tubePolygon(t,Math.max(width*.45,font*.07)))}" fill="#122d40"/>`;
        html+=`<g data-kind="strut" data-id="${esc(t.id)}" tabindex="0" role="button" aria-label="${esc(t.label)} ${labels[t.status]}"><title>${esc(t.label)} · ${labels[t.status]}</title><g mask="url(#wm-interior)">${tube}</g><line x1="${t.a[0]}" y1="${t.a[1]}" x2="${t.b[0]}" y2="${t.b[1]}" stroke="transparent" stroke-width="${Math.max(width,font)}"/>${!compact||active?`<text x="${middle[0]}" y="${middle[1]-font*.7}" font-size="${font}" text-anchor="middle">${esc(t.label)}</text>`:''}</g>`;
        if(active)for(const [i,p] of [t.a,t.b].entries())html+=`<circle cx="${p[0]}" cy="${p[1]}" r="${font*.3}" fill="#ff557a"/><text x="${p[0]+font*.6}" y="${p[1]-font*.5}" font-size="${font}">${i?'B':'A'}</text>`;
      }
    }
    if($('wm-wells').checked)for(const w of data.works.wells){
      html+=`<g data-kind="well" data-id="${esc(w.id)}" tabindex="0" role="button" aria-label="${esc(w.label)}"><circle cx="${w.point[0]}" cy="${w.point[1]}" r="${font*.6}" fill="${w.status==='planned'?'#164252':'#2a8292'}" stroke="${selection?.id===w.id?'#ff557a':'#6be4eb'}" stroke-width="2" vector-effect="non-scaling-stroke"/><text x="${w.point[0]}" y="${w.point[1]-font}" font-size="${font}" text-anchor="middle">${esc(w.label)}</text></g>`;
    }
    if(mode?.points)for(const p of mode.points)html+=`<circle cx="${p.point[0]}" cy="${p.point[1]}" r="${font*.4}" fill="#ffa75a"/>`;
    $('wm-map').innerHTML=html;
    const buttons=[...( $('wm-struts').checked?(level()?.struts||[]).map(s=>({kind:'strut',id:s.id,label:s.label})):[]),...($('wm-wells').checked?data.works.wells.map(w=>({kind:'well',id:w.id,label:w.label})):[])];
    $('wm-selectors').innerHTML=buttons.map(b=>`<button class="btn btn-secondary" data-kind="${b.kind}" data-id="${esc(b.id)}" aria-pressed="${selection?.id===b.id}">${esc(b.label)}</button>`).join('');
  }
  function facts(entries){return '<dl class="wm-facts">'+entries.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')+'</dl>';}
  function detail(){
    const s=strut(),well=selection?.kind==='well'?data.works.wells.find(w=>w.id===selection.id):null,p=selection?.kind==='panel'?panel(selection.id):null;
    let html='';
    if(s){
      html=`<h2>${esc(s.label)} · ${esc(level().name)}</h2>`+facts([
        ['Stato',labels[s.status]],['Asse puntone',level().axis_ngf==null?'Da indicare':num(level().axis_ngf)+' NGF'],['Appoggio A',panel(s.panel_a)?.label],['Appoggio B',panel(s.panel_b)?.label],['Lunghezza',num(s.length_m)+' m'],['Diametro esterno',num(s.diameter_mm)+' mm'],['Spessore tubo',num(s.thickness_mm)+' mm'],['Angoli in pianta A / B',num(s.angle_a)+'° / '+num(s.angle_b)+'°'],['Fissaggi A / B',(s.fixation_a||'—')+' / '+(s.fixation_b||'—')],['Vériné · dato del PDF',s.verine||'Da completare'],['Posa',s.installed_on||'—'],['Rimozione',s.removed_on||'—']]);
      html+=`<p>${esc(s.notes)}</p>${s.source_id?`<p><a href="${url}/pdf/${s.source_id}/originale" target="_blank" rel="noopener">Apri PDF di riferimento</a></p>`:''}`;
    }else if(well){html=`<h2>${esc(well.label)}</h2>`+facts([['Stato',labels[well.status]],['Note',well.notes||'—']]);}
    else if(p){const e=data.elements.find(x=>x.number===p.element);html=`<h2>Pannello ${esc(p.label)}</h2>`+facts([['Paratia',e?.status==='cast'?'Getto registrato':e?.status==='fiche'?'Fiche presente':'Da eseguire'],['Rabotage',data.works.rabotage.includes(p.element)?'Completato':'Da eseguire']]);if(data.can_edit&&p.element)html+=`<button class="btn btn-primary" id="wm-treat">${data.works.rabotage.includes(p.element)?'Segna rabotage da eseguire':'Segna rabotage completato'}</button>`;}
    else html='<h2>Dettagli dell’elemento</h2><p>Seleziona un puntone per vedere misure e appoggi, un pozzo per il pompaggio o un pannello per il rabotage.</p>';
    if(data.can_edit&&(s||well))html+='<div class="wm-row wm-actions"><button class="btn btn-primary" id="wm-change">Modifica dati e stato</button><button class="btn btn-secondary" id="wm-move">Riposiziona sulla mappa</button><button class="btn btn-danger" id="wm-delete">Elimina elemento</button></div>';
    $('wm-detail').innerHTML=html;
    $('wm-change')?.addEventListener('click',()=>s?editStrut(copy(s)):editWell(copy(well)));
    $('wm-move')?.addEventListener('click',()=>{mode={kind:s?'strut':'well',item:copy(s||well),points:[]};placement();});
    $('wm-delete')?.addEventListener('click',()=>action(async()=>{
      if(!await confirm(`Eliminare ${s?.label||well.label} e i suoi dati dalla mappa? La pianta delle paratie e il PDF restano conservati.`))return;
      const v=copy(data.works),id=s?.id||well.id;if(s)v.levels.find(l=>l.id===levelId).struts=v.levels.find(l=>l.id===levelId).struts.filter(t=>t.id!==id);else v.wells=v.wells.filter(w=>w.id!==id);
      await save(v,[id]);selection=null;detail();
    }));
    $('wm-treat')?.addEventListener('click',()=>action(async()=>{const v=copy(data.works);v.rabotage=v.rabotage.includes(p.element)?v.rabotage.filter(n=>n!==p.element):[...v.rabotage,p.element];await save(v);}));
  }
  async function confirm(text){$('wm-confirm-text').textContent=text;const d=$('wm-confirm');d.showModal();return new Promise(resolve=>d.addEventListener('close',()=>resolve(d.returnValue==='confirm'),{once:true}));}
  function field(label,name,value='',type='text',extra=''){return `<label>${esc(label)}<input name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></label>`;}
  function options(name,label,values,value){return `<label>${esc(label)}<select name="${name}">${values.map(([v,text])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;}
  const supportOptions=()=>panels().slice().sort((a,b)=>a.label.localeCompare(b.label,'it',{numeric:true})).map(p=>[p.key,p.label]);
  function editor(title,fields,submit){$('wm-form-title').textContent=title;$('wm-fields').innerHTML=fields;$('wm-form-error').textContent='';formSubmit=submit;$('wm-editor').showModal();}
  $('wm-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=e.submitter;if(button.disabled)return;button.disabled=true;
    try{await formSubmit(new FormData(e.target));$('wm-editor').close();}catch(error){$('wm-form-error').textContent=error.message;}finally{button.disabled=false;}
  });
  function editLevel(existing){
    const l=existing||{id:uid(),name:`Livello -${data.works.levels.length+1}`,axis_ngf:null,struts:[]};
    editor(existing?'Modifica livello':'Nuovo livello',field('Nome','name',l.name,'text','required maxlength="80"')+field('Quota asse puntone (NGF)','axis_ngf',l.axis_ngf,'number','step="0.01" min="-10000" max="10000"'),async f=>{
      const v=copy(data.works),item={...l,name:f.get('name').trim(),axis_ngf:f.get('axis_ngf')===''?null:Number(f.get('axis_ngf'))};
      const i=v.levels.findIndex(x=>x.id===l.id);if(i<0)v.levels.push(item);else v.levels[i]=item;
      await save(v);levelId=l.id;render();
    });
  }
  function newStrut(){return {id:uid(),label:'',panel_a:'',panel_b:'',a:[0,0],b:[0,0],length_m:null,diameter_mm:null,thickness_mm:null,angle_a:null,angle_b:null,fixation_a:'',fixation_b:'',verine:'',status:'planned',installed_on:null,removed_on:null,notes:'',source_id:null};}
  function editStrut(s,proposal=null){
    const lId=levelId;
    let fields=field('Sigla puntone','label',s.label,'text','required maxlength="80"')+options('status','Stato',Object.entries(labels).filter(([k])=>['planned','installed','removed'].includes(k)),s.status);
    fields+=options('panel_a','Pannello appoggio A',[['','Scegli…'],...supportOptions()],s.panel_a)+options('panel_b','Pannello appoggio B',[['','Scegli…'],...supportOptions()],s.panel_b);
    for(const [k,text] of [['length_m','Lunghezza (m)'],['diameter_mm','Diametro esterno (mm)'],['thickness_mm','Spessore tubo (mm)'],['angle_a','Angolo in pianta A (°)'],['angle_b','Angolo in pianta B (°)']])fields+=field(text,k,s[k],'number',`step="0.01" min="${k.startsWith('angle')?0:.01}" max="${k.startsWith('angle')?180:100000}"`);
    fields+=field('Fissaggio A · riferimento PDF','fixation_a',s.fixation_a,'text','maxlength="100"')+field('Fissaggio B · riferimento PDF','fixation_b',s.fixation_b,'text','maxlength="100"')+field('Vériné · testo o valore con unità del PDF','verine',s.verine,'text','maxlength="150"')+field('Data posa','installed_on',s.installed_on,'date')+field('Data rimozione','removed_on',s.removed_on,'date')+`<label class="wm-span">Note<textarea name="notes" maxlength="2000">${esc(s.notes)}</textarea></label>`;
    if(proposal)fields+='<p class="wm-span">Importando una revisione, stato, date e note del puntone esistente resteranno conservati. Un nuovo puntone parte da “Da eseguire”.</p>';
    editor(proposal?'Controlla proposta PDF':'Puntone · dati e avanzamento',fields,async f=>{
      const item={...s};for(const key of ['label','panel_a','panel_b','fixation_a','fixation_b','verine','status','notes'])item[key]=f.get(key).trim();
      for(const key of ['length_m','diameter_mm','thickness_mm','angle_a','angle_b'])item[key]=f.get(key)===''?null:Number(f.get(key));
      for(const key of ['installed_on','removed_on'])item[key]=f.get(key)||null;
      for(const end of ['a','b'])if(item['panel_'+end]!==s['panel_'+end]&&panel(item['panel_'+end]))item[end]=center(panel(item['panel_'+end]));
      if(!item.panel_a||!item.panel_b)throw Error('Scegli entrambi i pannelli di appoggio.');
      if(proposal){proposal.value=item;proposal.reviewed=true;readerTable();readerMaps();return;}
      const v=copy(data.works),list=v.levels.find(l=>l.id===lId).struts,i=list.findIndex(t=>t.id===item.id);if(i<0)list.push(item);else list[i]=item;
      await save(v);selection={kind:'strut',id:item.id};mode=null;placement();draw();detail();
    });
  }
  function editWell(w){
    editor('Pozzo · dati e avanzamento',field('Nome pozzo','label',w.label,'text','required maxlength="80"')+options('status','Stato',['planned','completed','pumping','stopped'].map(s=>[s,labels[s]]),w.status)+`<label class="wm-span">Note<textarea name="notes" maxlength="2000">${esc(w.notes)}</textarea></label>`,async f=>{
      const v=copy(data.works),item={...w,label:f.get('label').trim(),status:f.get('status'),notes:f.get('notes').trim()},i=v.wells.findIndex(x=>x.id===w.id);if(i<0)v.wells.push(item);else v.wells[i]=item;
      await save(v);selection={kind:'well',id:w.id};mode=null;placement();draw();detail();
    });
  }
  function placement(){
    $('wm-placement').innerHTML=mode?`${mode.kind==='well'?'Tocca il punto dove posizionare il pozzo.':`Tocca il pannello di appoggio ${mode.points.length?'B':'A'} nella posizione desiderata.`} <button class="btn btn-secondary" id="wm-cancel-placement">Annulla</button>`:'';
    $('wm-cancel-placement')?.addEventListener('click',()=>{mode=null;placement();draw();});
    if(mode)$('wm-map').scrollIntoView({block:'center',behavior:'smooth'});
  }
  function point(event,svg){const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.getScreenCTM().inverse());return [p.x,p.y];}
  function closest(p){let best=null;for(const q of panels())for(let i=0;i<q.points.length;i++){
    const a=q.points[i],b=q.points[(i+1)%q.points.length],dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))),hit=[a[0]+t*dx,a[1]+t*dy],d=dist(p,hit);
    if(!best||d<best.distance)best={panel:q.key,point:hit,distance:d};
  }return best;}
  function pick(event){
    if(busy)return;
    if(mode&&event.currentTarget===$('wm-map')){
      const p=point(event,$('wm-map'));
      if(mode.kind==='well'){const next=1+Math.max(0,...data.works.wells.map(w=>Number(w.label.match(/^Pozzo (\d+)$/)?.[1]||0)));const w=mode.item||{id:uid(),label:`Pozzo ${next}`,status:'planned',notes:''};editWell({...w,point:p});return;}
      const hit=closest(p),box=view||fullBox();if(!hit||hit.distance>Math.max(box[2],box[3])*.035){message('Tocca un pannello di appoggio.');return;}
      mode.points.push(hit);draw();placement();if(mode.points.length===2){const s=mode.item||newStrut();s.a=mode.points[0].point;s.panel_a=mode.points[0].panel;s.b=mode.points[1].point;s.panel_b=mode.points[1].panel;mode.points=[];editStrut(s);}return;
    }
    const node=event.target.closest('[data-kind]');if(!node)return;selection={kind:node.dataset.kind,id:node.dataset.id};draw();detail();
  }
  $('wm-map').addEventListener('click',pick);$('wm-selectors').addEventListener('click',pick);
  $('wm-map').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(e);}});
  $('wm-fit').onclick=()=>{view=null;draw();};$('wm-zoom').onclick=()=>{
    const s=strut(),w=data.works.wells.find(w=>w.id===selection?.id),p=panel(selection?.id);view=s?bbox([s.a,s.b],.16):w?bbox([w.point,[w.point[0]+fullBox()[2]*.12,w.point[1]+fullBox()[3]*.12]],.6):p?bbox(p.points,.5):null;draw();
  };
  for(const end of ['a','b'])$('wm-zoom-'+end).onclick=()=>{const s=strut();if(!s)return;const p=s[end],size=Math.max(...fullBox().slice(2))*.22;view=[p[0]-size/2,p[1]-size/2,size,size];draw();};
  $('wm-level').onchange=e=>{levelId=e.target.value;selection=null;mode=null;placement();render();};
  for(const id of ['wm-struts','wm-wells','wm-rabotage'])$(id).onchange=()=>draw();
  $('wm-add-level')?.addEventListener('click',()=>editLevel());$('wm-edit-level')?.addEventListener('click',()=>editLevel(copy(level())));
  $('wm-add-strut')?.addEventListener('click',()=>{mode={kind:'strut',points:[]};$('wm-struts').checked=true;placement();});
  $('wm-add-well')?.addEventListener('click',()=>{mode={kind:'well',points:[]};$('wm-wells').checked=true;placement();});
  document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());

  // PDF proposals stay outside persistent work state until explicit review.
  $('wm-read')?.addEventListener('click',()=>{$('wm-reader').showModal();});
  $('wm-sources').addEventListener('click',e=>{const b=e.target.closest('[data-reread]');if(!b)return;if(!level()){message('Crea prima un livello di puntoni.');return;}reader={id:Number(b.dataset.reread)};$('wm-reader').showModal();reread(null);});
  function setReader(result){
    reader={...result,rows:result.struts.map(s=>({raw:s,value:{...newStrut(),label:s.label,length_m:s.length_m,diameter_mm:s.diameter_mm,thickness_mm:s.thickness_mm,angle_a:s.angle_a??null,angle_b:s.angle_b??null,source_id:result.id},selected:true,reviewed:false}))};
    sourceAnchors=[];targetAnchors=[];crop=null;proposalIndex=0;reposition=false;$('wm-import-reviewed').checked=false;$('wm-read-content').hidden=false;
    $('wm-original').href=`${url}/pdf/${reader.id}/originale`;$('wm-reader-notice').textContent=reader.notice;$('wm-evidence').textContent=reader.evidence;
    $('wm-pdf').setAttribute('viewBox',`0 0 ${reader.width} ${reader.height}`);$('wm-target').setAttribute('viewBox',fullBox().join(' '));readerTable();readerMaps();
    $('wm-read-status').textContent=`${reader.rows.length} proposte. Allinea i due disegni, poi controlla i singoli puntoni.`;
  }
  $('wm-upload').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;$('wm-read-status').textContent='Lettura del PDF in corso…';try{setReader(await api('/leggi-pdf',{method:'POST',body:new FormData(e.target)}));await refreshSources();}catch(err){$('wm-read-status').textContent=err.message;}finally{b.disabled=false;}};
  async function refreshSources(){const fresh=await api('/data');data.sources=fresh.sources;render();}
  async function reread(region){$('wm-read-status').textContent='Lettura della selezione…';try{setReader(await api(`/pdf/${reader.id}/rileggi`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({crop:region})}));}catch(e){$('wm-read-status').textContent=e.message;}}
  $('wm-crop-read').onclick=()=>{if(crop)reread(crop);else $('wm-read-status').textContent='Traccia prima un rettangolo sul PDF.';};$('wm-page-read').onclick=()=>reader&&reread(null);
  function transform(p){
    const [a,b]=sourceAnchors,[c,d]=targetAnchors,dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy;
    const re=((d[0]-c[0])*dx+(d[1]-c[1])*dy)/den,im=((d[1]-c[1])*dx-(d[0]-c[0])*dy)/den;
    return [c[0]+re*(p[0]-a[0])-im*(p[1]-a[1]),c[1]+im*(p[0]-a[0])+re*(p[1]-a[1])];
  }
  function align(){
    if(sourceAnchors.length!==2||targetAnchors.length!==2)return;
    if(dist(...sourceAnchors)<10||dist(...targetAnchors)<10){$('wm-align-state').textContent='Scegli due punti più distanti.';return;}
    for(const row of reader.rows){
      row.reviewed=false;
      if(!row.raw.a||!row.raw.b)continue;
      row.value.a=transform(row.raw.a);row.value.b=transform(row.raw.b);
      for(const end of ['a','b']){const near=closest(row.value[end]);row.value['panel_'+end]=near&&near.distance<Math.max(...fullBox().slice(2))*.035?near.panel:'';}
    }
    $('wm-import-reviewed').checked=false;$('wm-align-state').textContent='Allineamento proposto: controlla sulla mappa tutti gli appoggi.';readerTable();readerMaps();
  }
  function alignmentHelp(){
    $('wm-align-help').textContent=$('wm-pdf-mode').value==='crop'?'Trascina sul PDF per selezionare la sola pianta dei puntoni.':sourceAnchors.length<2?`Tocca sul PDF il punto ${sourceAnchors.length+1} (scegli due angoli riconoscibili e distanti).`:targetAnchors.length<2?`Tocca sulla pianta convalidata lo stesso punto ${targetAnchors.length+1}, nello stesso ordine.`:'Confronta la sovrapposizione. Puoi correggere gli appoggi o riposizionare ogni puntone. Rotella: zoom sulle due mappe.';
  }
  $('wm-pdf-mode').onchange=alignmentHelp;
  $('wm-align-reset').onclick=()=>{sourceAnchors=[];targetAnchors=[];reposition=false;$('wm-pdf-mode').value='align';$('wm-align-state').textContent='Allineamento da verificare';for(const r of reader?.rows||[])r.reviewed=false;$('wm-import-reviewed').checked=false;readerMaps();readerTable();};
  function readerMaps(){
    if(!reader)return;const font=Math.max(reader.width,reader.height)/80;
    let pdf=`<image href="${url}/pdf/${reader.id}/anteprima" x="0" y="0" width="${reader.width}" height="${reader.height}"/>`;
    if(crop)pdf+=`<rect x="${crop[0]*reader.width}" y="${crop[1]*reader.height}" width="${(crop[2]-crop[0])*reader.width}" height="${(crop[3]-crop[1])*reader.height}" stroke="#ed265c" stroke-width="3" fill="#ed265c15" vector-effect="non-scaling-stroke"/>`;
    const raw=reader.rows[proposalIndex]?.raw;if(raw?.a&&raw?.b)pdf+=`<line x1="${raw.a[0]}" y1="${raw.a[1]}" x2="${raw.b[0]}" y2="${raw.b[1]}" stroke="#ef3258" stroke-width="4" vector-effect="non-scaling-stroke"/>`;
    for(const [i,p]of sourceAnchors.entries())pdf+=`<circle cx="${p[0]}" cy="${p[1]}" r="${font*.5}" fill="#e53256"/><text x="${p[0]+font}" y="${p[1]}" font-size="${font}" fill="#dc234e">${i+1}</text>`;
    $('wm-pdf').innerHTML=pdf;let target=panelShapes([],false,Math.max(...fullBox().slice(2))/80);
    for(const [i,p]of targetAnchors.entries())target+=`<circle cx="${p[0]}" cy="${p[1]}" r="${fullBox()[2]/100}" fill="#f58843"/><text x="${p[0]}" y="${p[1]}" font-size="${fullBox()[2]/50}">${i+1}</text>`;
    if(targetAnchors.length===2||reposition)for(const [i,r]of reader.rows.entries())if(r.selected&&r.value.panel_a&&r.value.panel_b){const s=r.value;target+=`<g data-row="${i}"><line x1="${s.a[0]}" y1="${s.a[1]}" x2="${s.b[0]}" y2="${s.b[1]}" stroke="${i===proposalIndex?'#ff557a':'#6daecb'}" stroke-width="${i===proposalIndex?4:2}" vector-effect="non-scaling-stroke"/><text x="${(s.a[0]+s.b[0])/2}" y="${(s.a[1]+s.b[1])/2}" font-size="${fullBox()[2]/65}">${esc(s.label)}</text></g>`;}
    $('wm-target').innerHTML=target;alignmentHelp();
    if(reposition)$('wm-align-help').textContent=`Puntone ${reader.rows[proposalIndex]?.value.label}: tocca l’appoggio ${reposition.length?'B':'A'} sulla pianta convalidata.`;
  }
  function readerTable(){
    if(!reader)return;
    $('wm-proposals').innerHTML=reader.rows.map((r,i)=>`<tr data-index="${i}" data-selected="${i===proposalIndex}"><td><input type="checkbox" data-prop="selected" aria-label="Importa ${esc(r.value.label)}" ${r.selected?'checked':''}></td><td><button class="btn btn-secondary" data-view-row="${i}">${esc(r.value.label)}</button></td>${['length_m','diameter_mm','thickness_mm'].map(k=>`<td><input type="number" step="0.01" min="0.01" data-prop="${k}" value="${r.value[k]??''}" aria-label="${k} ${esc(r.value.label)}"></td>`).join('')}${['a','b'].map(end=>`<td><select data-prop="panel_${end}" aria-label="Appoggio ${end} ${esc(r.value.label)}"><option value="">Da scegliere</option>${supportOptions().map(([id,l])=>`<option value="${esc(id)}" ${r.value['panel_'+end]===id?'selected':''}>${esc(l)}</option>`).join('')}</select></td>`).join('')}<td><button class="btn btn-secondary" data-edit-row="${i}">Dettagli</button> <button class="btn btn-secondary" data-place-row="${i}">Appoggi sulla mappa</button><label><input type="checkbox" data-prop="reviewed" ${r.reviewed?'checked':''}> Verificato</label></td></tr>`).join('')||'<tr><td colspan="8">Nessuna sigla B… leggibile. Usa “Aggiungi puntone” sulla mappa e conserva il PDF come riferimento.</td></tr>';
  }
  $('wm-proposals').addEventListener('change',e=>{
    const i=Number(e.target.closest('[data-index]')?.dataset.index),row=reader.rows[i],key=e.target.dataset.prop;if(!row||!key)return;
    if(['selected','reviewed'].includes(key))row[key]=e.target.checked;
    else{row.reviewed=false;$('wm-import-reviewed').checked=false;if(key.startsWith('panel_')){row.value[key]=e.target.value;if(panel(e.target.value))row.value[key.slice(-1)]=center(panel(e.target.value));}else row.value[key]=e.target.value===''?null:Number(e.target.value);}
    proposalIndex=i;readerMaps();if(!['selected','reviewed'].includes(key))readerTable();
  });
  $('wm-proposals').addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    const i=Number(b.dataset.viewRow??b.dataset.editRow??b.dataset.placeRow);proposalIndex=i;
    if(b.dataset.editRow!=null)editStrut(copy(reader.rows[i].value),reader.rows[i]);
    if(b.dataset.placeRow!=null){reposition=[];$('wm-target').scrollIntoView({block:'center',behavior:'smooth'});}
    readerTable();readerMaps();
  });
  $('wm-pdf').addEventListener('pointerdown',e=>{
    if(!reader)return;const p=point(e,$('wm-pdf'));
    if($('wm-pdf-mode').value==='align'){if(sourceAnchors.length<2)sourceAnchors.push(p);readerMaps();align();return;}
    drag=p;$('wm-pdf').setPointerCapture(e.pointerId);
  });
  $('wm-pdf').addEventListener('pointermove',e=>{if(!drag)return;const p=point(e,$('wm-pdf'));crop=[Math.min(drag[0],p[0])/reader.width,Math.min(drag[1],p[1])/reader.height,Math.max(drag[0],p[0])/reader.width,Math.max(drag[1],p[1])/reader.height].map(n=>Math.max(0,Math.min(1,n)));readerMaps();});
  $('wm-pdf').addEventListener('pointerup',()=>{drag=null;});$('wm-pdf').addEventListener('pointercancel',()=>{drag=null;});
  $('wm-target').addEventListener('click',e=>{
    if(!reader)return;const p=point(e,$('wm-target'));
    if(reposition){const hit=closest(p);if(!hit||hit.distance>Math.max(...fullBox().slice(2))*.04)return;reposition.push(hit);if(reposition.length===2){const row=reader.rows[proposalIndex];row.value.a=reposition[0].point;row.value.b=reposition[1].point;row.value.panel_a=reposition[0].panel;row.value.panel_b=reposition[1].panel;row.reviewed=false;reposition=false;$('wm-import-reviewed').checked=false;readerTable();}readerMaps();return;}
    if($('wm-pdf-mode').value==='align'&&sourceAnchors.length===2&&targetAnchors.length<2){targetAnchors.push(p);readerMaps();align();}
  });
  for(const svg of [$('wm-map'),$('wm-pdf'),$('wm-target')])svg.addEventListener('wheel',e=>{
    if(!data?.reference||svg!==$('wm-map')&&!reader)return;e.preventDefault();const p=point(e,svg),b=svg.viewBox.baseVal,k=e.deltaY>0?1.15:.87;
    const next=[p[0]+(b.x-p[0])*k,p[1]+(b.y-p[1])*k,b.width*k,b.height*k];if(next[2]<10||next[2]>20000)return;
    if(svg===$('wm-map')){view=next;draw();}else svg.setAttribute('viewBox',next.join(' '));
  },{passive:false});
  $('wm-import').onclick=async()=>{
    const rows=reader?.rows.filter(r=>r.selected)||[];
    if(!rows.length||!rows.every(r=>r.reviewed)||!$('wm-import-reviewed').checked){$('wm-read-status').textContent='Controlla ogni riga selezionata e conferma la verifica complessiva.';return;}
    if(rows.some(r=>!r.value.panel_a||!r.value.panel_b)){ $('wm-read-status').textContent='Completa gli appoggi di tutti i puntoni selezionati.';return;}
    const b=$('wm-import');b.disabled=true;
    try{
      const result=await api('/conferma-lettura',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body(data.works),level_id:levelId,source_id:reader.id,struts:rows.map(r=>r.value),reviewed:true})});
      data.works=result.works;data.revision=result.revision;$('wm-reader').close();render();message('Puntoni confermati. Le lavorazioni già registrate sono state conservate.');
    }catch(e){$('wm-read-status').textContent=e.message;}finally{b.disabled=false;}
  };
  new ResizeObserver(()=>{if(data?.reference&&$('wm-map').clientWidth)draw();}).observe($('wm-map'));
  load().catch(e=>message(e.message));
})();
