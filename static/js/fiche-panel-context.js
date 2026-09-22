/* Optional plan shortcut inside the existing fiche form. */
document.addEventListener('DOMContentLoaded', () => {
  const catalog=JSON.parse(document.getElementById('fiche-panel-catalog')?.textContent||'{}');
  const site=document.getElementById('cantiere_id'), number=document.getElementById('numero_pannello'), coupe=document.getElementById('coupe_id'), type=document.getElementById('tipologia_scavo');
  if(!site||!number)return;
  const picker=document.createElement('select');picker.className='form-select';picker.setAttribute('aria-label','Pannello della pianta');picker.style.marginTop='.5rem';number.after(picker);
  function update(){
    const panels=type?.value==='paratia'?(catalog[site.value]||[]):[];
    picker.replaceChildren(new Option('Seleziona dalla pianta',''));
    panels.forEach(p=>picker.add(new Option(`${p.label} · ${p.width_m} m`,p.number)));
    picker.value=number.value;picker.hidden=!panels.length;
    const selected=panels.find(p=>String(p.number)===number.value),label=selected?.label;
    const width=document.getElementById('larghezza_pannello');
    if(width&&document.querySelector('[data-fiche-form]').dataset.edit!=='true'){
      width.readOnly=!!selected?.width_m;
      if(selected?.width_m){width.value=selected.width_m;width.dataset.fromPlan='1';}
      else if(width.dataset.fromPlan){width.value='';delete width.dataset.fromPlan;}
    }
    const summary=document.querySelector('[data-summary-number]');if(summary&&label)summary.textContent=label;
  }
  picker.onchange=()=>{
    if(!picker.value)return;
    const p=catalog[site.value].find(p=>String(p.number)===picker.value);
    number.value=picker.value;
    const assigned=[...(coupe?.options||[])].find(o=>o.dataset.siteId===site.value&&o.dataset.assignments?.split(',').includes(`paratia:${number.value}`));
    if(coupe)coupe.value=assigned?.value||'';
    const scavo=document.getElementById('scavo_da_tn');if(scavo&&assigned)scavo.value=assigned.dataset.scavo;
    if(assigned){
      for(const [id,key] of Object.entries({profondita_totale:'profondita',quota_ngf_testa:'quotaTesta',quota_ngf_fondo:'quotaFondo',quota_testa_getto:'getto',altezza_pannello:'spessore'})){
        const field=document.getElementById(id);if(field)field.value=assigned.dataset[key]||'';
      }
    }
    const width=document.getElementById('larghezza_pannello');if(width&&p?.width_m)width.value=p.width_m;
    number.dispatchEvent(new Event('input',{bubbles:true}));coupe?.dispatchEvent(new Event('change',{bubbles:true}));update();
  };
  number.addEventListener('input',update);
  [site,number,type].forEach(el=>el?.addEventListener('change',update));
  function datum(){const saved=document.getElementById('fiche-panel-catalog').dataset;const ref=(saved.coupe===coupe?.value&&saved.datum)||coupe?.selectedOptions?.[0]?.dataset.datum||'NGF';document.querySelectorAll('label').forEach(label=>{if(!label.dataset.datumOriginal&&label.textContent.includes('NGF'))label.dataset.datumOriginal=label.textContent;if(label.dataset.datumOriginal)label.textContent=label.dataset.datumOriginal.replaceAll('NGF',ref);});}
  coupe?.addEventListener('change',datum);update();datum();
});
