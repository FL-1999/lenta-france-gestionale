/* Plan labels are the only visible reference; stable numbers remain internal. */
document.addEventListener('DOMContentLoaded', () => {
  const catalog=JSON.parse(document.getElementById('fiche-panel-catalog')?.textContent||'{}');
  const site=document.getElementById('cantiere_id'), number=document.getElementById('numero_pannello'), coupe=document.getElementById('coupe_id'), type=document.getElementById('tipologia_scavo');
  if(!site||!number)return;
  const picker=document.getElementById('fiche_panel');
  if(!picker)return;
  const label=document.querySelector('[data-panel-label]'),help=document.getElementById('fiche-panel-help');
  const placeholder=picker.options[0].textContent;
  let context=`${site.value}:${type?.value}`;
  function update(){
    const panels=type?.value==='paratia'?(catalog[site.value]||[]):[];
    picker.replaceChildren(new Option(placeholder,''));
    panels.forEach(p=>picker.add(new Option(p.label+(p.width_m?` · ${p.width_m} m`:'')+(p.unmapped?` · ${picker.dataset.unmappedLabel}`:''),p.number)));
    const fromPlan=panels.length>0;
    // Exactly one successful control: the picker submits its own stable value,
    // including without JS. The hidden mirror is only for existing coupe logic.
    picker.hidden=picker.disabled=!fromPlan;picker.required=fromPlan;
    number.type=fromPlan?'hidden':'number';number.disabled=fromPlan;number.required=!fromPlan;
    label.htmlFor=fromPlan?picker.id:number.id;help.hidden=!fromPlan;
    const selected=panels.find(p=>String(p.number)===number.value);
    help.textContent=selected?.unmapped?help.dataset.unmappedHelp:help.dataset.planHelp;
    if(fromPlan&&!selected)number.value='';
    picker.value=number.value;
    const width=document.getElementById('larghezza_pannello');
    if(width&&document.querySelector('[data-fiche-form]').dataset.edit!=='true'){
      width.readOnly=!!selected?.width_m;
      if(selected?.width_m){width.value=selected.width_m;width.dataset.fromPlan='1';}
      else if(width.dataset.fromPlan){width.value='';delete width.dataset.fromPlan;}
    }
    const summary=document.querySelector('[data-summary-number]');
    if(summary)summary.textContent=selected?.label||number.value||'—';
  }
  picker.onchange=()=>{
    const p=(catalog[site.value]||[]).find(p=>String(p.number)===picker.value);
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
  number.addEventListener('change',update);
  [site,type].forEach(el=>el?.addEventListener('change',()=>{
    const next=`${site.value}:${type?.value}`;
    if(next!==context){
      const [oldSite,oldType]=context.split(':');
      const hasPlan=type?.value==='paratia'&&(catalog[site.value]||[]).length>0;
      if((oldSite&&oldSite!==site.value)||(oldType&&oldType!==type?.value)||hasPlan){
        number.value='';if(coupe)coupe.value='';
      }
      context=next;
      number.dispatchEvent(new Event('input',{bubbles:true}));
      coupe?.dispatchEvent(new Event('change',{bubbles:true}));
    }
    update();
  }));
  function datum(){
    const saved=document.getElementById('fiche-panel-catalog').dataset;
    const ref=(saved.coupe===coupe?.value&&saved.datum)||coupe?.selectedOptions?.[0]?.dataset.datum||'NGF';
    document.querySelectorAll('label').forEach(label => {
      label.childNodes.forEach(node => {
        if (node.nodeType !== Node.TEXT_NODE) return;
        if (!node.datumOriginal && node.textContent.includes('NGF')) node.datumOriginal = node.textContent;
        if (node.datumOriginal) node.textContent = node.datumOriginal.replaceAll('NGF', ref);
      });
    });
  }
  coupe?.addEventListener('change',datum);update();datum();
});
