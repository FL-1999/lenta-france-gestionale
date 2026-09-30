(() => {
  'use strict';
  const form=document.querySelector('.project-config-form'); if(!form)return;
  const fr=document.documentElement.lang==='fr', t=(it,f)=>fr?f:it;
  const labels={nome:'Coupe',quota_tn:'TN',quota_testa:t('Testa paratia','Tête de paroi'),quota_fondo_teorica:'Base hydraulique',base_paroi_mecanique:'Base mécanique',profondita_teorica:t('Profondità scavo da TN','Profondeur depuis TN'),spessore:t('Spessore','Épaisseur')};
  const states=new WeakMap();
  const empty=()=>({reviewed:true,struts:[],treatment:{state:'unknown',top:null,bottom:null},source:{}});
  const number=input=>input.value.trim()===''?null:Number(input.value);
  function bind(card){
    if(states.has(card))return;
    const hidden=card.querySelector('[name=coupe_drawing_info]'), box=card.querySelector('[data-coupe-info]');
    let info=empty(); try{if(hidden.value)info=JSON.parse(hidden.value);}catch{/* Preserve malformed data for the server validation. */}
    const state={info,dirty:!!hidden.value}; states.set(card,state);
    const rows=box.querySelector('[data-strut-rows]'), review=box.querySelector('[data-coupe-reviewed]');
    function serialize(){
      if(!state.dirty)return;
      state.info.struts=[...rows.querySelectorAll('input')].map(number);
      state.info.treatment={state:box.querySelector('[data-treatment-state]').value,top:number(box.querySelector('[data-treatment-top]')),bottom:number(box.querySelector('[data-treatment-bottom]'))};
      state.info.reviewed=review.checked;
      hidden.value=JSON.stringify(state.info);
    }
    function count(){
      [...rows.children].forEach((row,i)=>row.querySelector('span').textContent=t('Livello','Niveau')+' −'+(i+1));
      box.querySelector('[data-strut-count]').textContent=rows.children.length+' '+t('livelli inseriti. Al salvataggio saranno ordinati per quota decrescente.','niveaux saisis. Ils seront classés par cote décroissante à l’enregistrement.');
    }
    function add(value=null){
      const row=document.createElement('div');row.dataset.strutRow='';
      const title=document.createElement('span');const input=document.createElement('input');input.type='number';input.step='.01';input.className='form-control';input.value=value??'';input.setAttribute('aria-label',t('Quota asse puntone (m)','Cote axe du buton (m)'));
      const remove=document.createElement('button');remove.type='button';remove.className='btn btn-secondary';remove.textContent=t('Rimuovi','Retirer');
      remove.onclick=()=>{row.remove();state.dirty=true;count();serialize();};
      row.append(title,input,remove);rows.append(row);count();
    }
    function render(){
      rows.replaceChildren();(state.info.struts||[]).forEach(add);count();
      const treatment=state.info.treatment||{};
      box.querySelector('[data-treatment-state]').value=treatment.state||'unknown';
      box.querySelector('[data-treatment-top]').value=treatment.top??'';
      box.querySelector('[data-treatment-bottom]').value=treatment.bottom??'';
      box.querySelector('[data-treatment-quotes]').hidden=treatment.state!=='present';
      review.checked=state.info.reviewed===true;
      box.querySelector('[data-coupe-review]').hidden=!state.info.source?.filename;
      box.querySelector('[data-coupe-source]').textContent=state.info.source?.filename?`${state.info.source.filename} · ${t('pagina','page')} ${state.info.source.page}`:'';
    }
    box.querySelector('[data-add-strut]').onclick=()=>{add();state.dirty=true;serialize();};
    box.addEventListener('input',()=>{state.dirty=true;box.querySelector('[data-treatment-quotes]').hidden=box.querySelector('[data-treatment-state]').value!=='present';serialize();});
    state.render=render;state.serialize=serialize;
    const heights=()=>{
      const get=n=>number(card.querySelector(`[name=coupe_${n}]`));
      const head=get('quota_testa'),base=get('quota_fondo_teorica'),mech=get('base_paroi_mecanique');
      const values=[];
      if(head!==null&&mech!==null)values.push(`H mécanique : ${(head-mech).toFixed(2)} m`);
      if(head!==null&&base!==null)values.push(`H totale : ${(head-base).toFixed(2)} m`);
      if(mech!==null&&base!==null)values.push(`H hydraulique : ${(mech-base).toFixed(2)} m`);
      card.querySelector('[data-coupe-heights]').textContent=values.join(' · ');
    };
    card.addEventListener('input',heights);state.heights=heights;
    card.querySelector('[data-read-coupe-pdf]').onclick=()=>open(card);
    render();heights();
  }
  form.querySelectorAll('[data-coupe-card]').forEach(bind);
  document.addEventListener('coupe-added',event=>bind(event.detail));
  form.addEventListener('submit',()=>form.querySelectorAll('[data-coupe-card]').forEach(card=>states.get(card)?.serialize()));

  const dialog=document.querySelector('#coupe-pdf-reader'), q=s=>dialog.querySelector(s);
  let target=null, result=null, crop=null, start=null, busy=false;
  const invalidate=()=>{result=null;q('[data-reader-apply]').disabled=true;};
  function open(card){target=card;invalidate();crop=null;start=null;q('[data-reader-file]').value='';q('[data-reader-page]').value=1;q('[data-reader-page]').removeAttribute('max');q('[data-reader-message]').textContent='';q('.reader-body').hidden=true;q('[data-reader-selection]').hidden=true;dialog.showModal();}
  q('[data-reader-close]').onclick=()=>{if(!busy)dialog.close();};
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  function mark(){const rect=q('[data-reader-selection]');rect.hidden=!crop;if(crop)Object.assign(rect.style,{left:crop[0]*100+'%',top:crop[1]*100+'%',width:(crop[2]-crop[0])*100+'%',height:(crop[3]-crop[1])*100+'%'});}
  const preview=q('.reader-preview');
  const point=event=>{const r=preview.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))];};
  preview.onpointerdown=event=>{if(busy)return;start=point(event);preview.setPointerCapture(event.pointerId);invalidate();};
  preview.onpointermove=event=>{if(!start)return;const p=point(event);crop=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];mark();};
  preview.onpointerup=()=>{start=null;};preview.onpointercancel=()=>{start=null;};
  q('[data-reader-file]').onchange=()=>{invalidate();crop=null;q('[data-reader-page]').value=1;q('[data-reader-page]').removeAttribute('max');q('.reader-body').hidden=true;};
  q('[data-reader-page]').oninput=()=>{invalidate();crop=null;mark();q('.reader-body').hidden=true;};
  async function load(region){
    if(busy)return;
    invalidate();const file=q('[data-reader-file]').files[0], page=Number(q('[data-reader-page]').value);
    if(!file||file.size>15*1024*1024||!Number.isInteger(page)||page<1){q('[data-reader-message]').textContent=t('Scegli un PDF fino a 15 MB e una pagina valida.','Choisissez un PDF de 15 Mo maximum et une page valide.');return;}
    busy=true;dialog.querySelectorAll('button,input').forEach(e=>e.disabled=true);
    q('[data-reader-message]').textContent=t('Lettura in corso…','Lecture en cours…');
    try{
      const data=new FormData();data.append('file',file);data.append('page_number',String(page));if(region)data.append('crop',JSON.stringify(region));
      const response=await fetch(`/manager/cantieri/${form.dataset.site}/coupe/leggi-pdf`,{method:'POST',body:data,headers:{'X-Coupe-Reader':'1'}});
      const answer=await response.json();if(!response.ok)throw new Error(typeof answer.detail==='string'?answer.detail:t('Lettura non riuscita.','Lecture impossible.'));
      result=answer;result.source={filename:file.name,page};crop=region;
      q('[data-reader-image]').src='data:image/png;base64,'+answer.preview;
      q('[data-reader-page]').max=answer.page_count;q('.reader-body').hidden=false;mark();
      const list=q('[data-reader-values]');list.replaceChildren();
      for(const [key,value] of Object.entries(answer.fields)){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=labels[key]||key;dd.textContent=String(value)+(key==='nome'?'':' m');list.append(dt,dd);}
      const strut=document.createElement('p');strut.textContent=t('Assi puntoni','Axes des butons')+': '+(answer.struts.join(' / ')||t('da verificare','à vérifier'));list.append(strut);
      const treatment=document.createElement('p');treatment.textContent='Traitement : '+(answer.treatment.state==='present'?t('presente','présent')+' · '+[answer.treatment.top,answer.treatment.bottom].filter(v=>v!=null).join(' / '):t('da verificare','à vérifier'));list.append(treatment);
      for(const [selector,items] of [['[data-reader-warnings]',answer.warnings.map(s=>s.includes(' / ')?s.split(' / ')[fr?1:0]:s)],['[data-reader-evidence]',answer.evidence.map(e=>e.text)]]){const list=q(selector);list.replaceChildren();items.forEach(text=>{const li=document.createElement('li');li.textContent=text;list.append(li);});}
      q('[data-reader-message]').textContent=t('Lettura completata: controlla il disegno e le proposte.','Lecture terminée : vérifiez le dessin et les propositions.');
    }catch(error){q('[data-reader-message]').textContent=error.message;}
    finally{busy=false;dialog.querySelectorAll('button,input').forEach(e=>e.disabled=false);q('[data-reader-apply]').disabled=!result||result.blocked;}
  }
  q('[data-reader-load]').onclick=()=>load(null);
  q('[data-reader-crop]').onclick=()=>{if(crop)load(crop);else q('[data-reader-message]').textContent=t('Traccia prima un rettangolo.','Tracez d’abord un rectangle.');};
  q('[data-reader-reset]').onclick=()=>load(null);
  q('[data-reader-apply]').onclick=()=>{
    if(!result||result.blocked||!target)return;
    for(const [key,value] of Object.entries(result.fields)){const field=target.querySelector(`[name=coupe_${key}]`);if(field){field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));}}
    target.querySelector('[name=coupe_scavo_da_tn]').value='1';
    target.querySelector('[name=coupe_quota_reference_label]').value='NGF';
    target.querySelector('[name=coupe_quota_fondo_teorica]').dataset.manual='1';
    const state=states.get(target);state.info={reviewed:false,struts:result.struts.length?result.struts:(state.info.struts||[]),treatment:result.treatment.state!=='unknown'?result.treatment:state.info.treatment,source:result.source};state.dirty=true;state.render();state.serialize();state.heights();
    dialog.close();target.querySelector('[data-coupe-review]').scrollIntoView({block:'center',behavior:'smooth'});
  };
})();
