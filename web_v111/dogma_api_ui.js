import {ALL_FAMILIES,copy,families,plannedJobs,compileBatch,validateState,titleParts,todayCode,filterResults,migrateState,activeReferences} from './dogma_api_core.js?v=1.0.54';
import {icon} from './dogma_api_icons.js?v=1.0.54';
import {hoverCompare,openViewer} from './dogma_api_viewer.js?v=1.0.54';
import {referenceEditor} from './dogma_api_reference_editor.js?v=1.0.54';

export const el=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
export const btn=(text,fn,cls='',aria=text)=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;b.setAttribute('aria-label',aria);b.title=aria;return b;};
export const ib=(name,label,fn,cls='')=>{const b=btn('',fn,'dap-icon-button '+cls,label);b.append(icon(name));return b;};
const terminal=new Set(['completed','failed','cancelled','missing']);
const enumValues={aspect_ratio:['auto','1:1','2:3','3:2','3:4','4:3','4:5','5:4','9:16','16:9','21:9'],resolution:['1K','2K','4K'],'model.background':['auto','opaque','transparent'],'model.quality':['low','medium','high'],'model.size':['auto','1024x1024','1536x1024','1024x1536','2048x2048','2048x1152','1152x2048','3840x2160','2160x3840','Custom'],'model.size_preset':['Custom'],'model.resolution':['480p','720p','1080p','4k'],'model.ratio':['adaptive','16:9','4:3','1:1','3:4','9:16','21:9'],'model.task_type':['reference','edit','extend','auto'],'model.output_format':['mp4'],response_modalities:['IMAGE','IMAGE+TEXT']};
const displayName=k=>({'model.task_type':'TASK','model.generate_audio':'AUDIO','model.duration':'DURATION / SEC','model.auto_downscale':'AUTO DOWNSCALE','model.auto_upscale':'AUTO UPSCALE'})[k]||k.replace(/^model\./,'').replaceAll('_',' ').toUpperCase();
export class PlatformUI {
 constructor(bridge){this.bridge=bridge;this.state=bridge.load();this.library=[];this.selection=[];this.cards=new Map();this.urls=new Set();this.closed=false;this.busy=false;}
 save(){if(!this.closed)this.bridge.save(this.state);}
 async open(){
  await this.bridge.initialize?.(this.state);this.state=migrateState(this.state);
  this.root=el('dialog','','dap');this.root.setAttribute('aria-label','DOGMA API Platform');
  this.root.addEventListener('cancel',e=>{e.preventDefault();this.close();});
  this.root.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});
  this.root.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)this.addReferences([...e.dataTransfer.files]);});
  document.body.append(this.root);this.build();this.root.tabIndex=-1;this.root.showModal();this.root.focus({preventScroll:true});
  this.unsubscribe=this.bridge.subscribe?.((name,d)=>this.event(name,d));
  await Promise.allSettled([this.recover(),this.refreshLibrary(),this.refreshCredits()]);
  this.timer=setInterval(()=>{this.updateCards();this.refreshPrices();if(this.state.results.some(r=>!terminal.has(r.status)))this.recover();},1800);
  this.creditTimer=setInterval(()=>this.refreshCredits(),30000);
 }
 close(){if(this.closed)return;this.save();this.closed=true;clearInterval(this.timer);clearInterval(this.creditTimer);this.unsubscribe?.();this.modal?.close();this.root.close();this.root.remove();for(const u of this.urls)URL.revokeObjectURL(u);this.bridge.close?.();}
 note(text,bad=false){if(!this.notice)return;this.notice.textContent=text;this.notice.classList.toggle('is-error',bad);}
 build(){
  const header=el('header','','dap-header'),brand=el('div','','dap-brand'),logo=el('img');logo.src=this.bridge.logo();logo.alt='DOGMA';brand.append(logo,el('span','API Platform'));
  const actions=el('div','','dap-actions');this.credit=btn('CREDITS —',()=>this.refreshCredits(),'dap-credit','Aggiorna crediti');
  this.runButton=btn('',()=>this.run(),'dap-run','Avvia generazioni in parallelo');this.runLabel=el('span','Run');this.runButton.append(this.runLabel,icon('play'));
  actions.append(this.credit,ib('download','Salva sessione e workflow',()=>this.bridge.download(this.state)),ib('close','Torna a Comfy',()=>this.close()),this.runButton);header.append(brand,actions);
  const layout=el('div','','dap-layout');this.side=el('aside','','dap-side');const tabs=el('nav','','dap-tabs');
  this.imageTab=btn('',()=>this.switchMode('image'),'','Image');this.imageTab.append(icon('image'),el('span','Image'));this.videoTab=btn('',()=>this.switchMode('video'),'','Video');this.videoTab.append(icon('video'),el('span','Video'));tabs.append(this.imageTab,this.videoTab);
  this.editRow=el('div','','dap-edit-mode');this.editRow.append(this.toggle('Image Edit',this.state.imageEdit,v=>{this.state.imageEdit=v;this.save();}),el('span','Image Edit'),el('small','Image 1 → compare'));
  this.controls=el('div','','dap-controls');this.side.append(tabs,this.editRow,this.controls);
  const main=el('main','','dap-main'),toolbar=el('div','','dap-toolbar');this.context=el('div','','dap-project');
  const views=el('div','','dap-views');this.ab=ib('compare','Confronta due risultati',()=>this.compare());
  const slider=this.slider=el('input');slider.type='range';slider.min='0';slider.max='100';slider.step='any';slider.value=String(this.state.density);slider.setAttribute('aria-label','Dimensione delle immagini');
  slider.oninput=()=>{this.state.density=Number(slider.value);this.applyDensity();this.save();};
  views.append(this.ab,ib('single','Una immagine grande',()=>{slider.value='0';slider.oninput();}),slider,ib('grid','Griglia compatta',()=>{slider.value='100';slider.oninput();}));toolbar.append(this.context,views);
  this.filters=el('div','','dap-filters');this.notice=el('div','','dap-notice');this.notice.setAttribute('role','status');
  this.galleryViewport=el('div','','dap-gallery-viewport');this.gallery=el('div','','dap-gallery');this.galleryViewport.append(this.gallery);
  main.append(toolbar,this.filters,this.notice,this.galleryViewport);layout.append(this.side,main);this.root.append(header,layout);
  this.renderControls();this.renderFilters();this.renderGallery();this.updateHeader();this.applyDensity();
  this.resize=new ResizeObserver(()=>this.applyDensity());this.resize.observe(this.galleryViewport);this.root.addEventListener('close',()=>this.resize.disconnect(),{once:true});
  this.note(this.bridge.preview?'ANTEPRIMA · Immagini dal tuo design · Nessuna richiesta API':'Reference, parametri e cartella pronti.');
 }
 applyDensity(){if(!this.gallery)return;const columns=1+3*Number(this.state.density)/100,width=(this.galleryViewport.clientWidth||1400)/columns;this.gallery.style.setProperty('--card-min',Math.max(170,width-18)+'px');this.slider.title=`Dimensione galleria / ${Math.round(width)} px`;}
 updateHeader(){const s=this.state;this.context.textContent=[s.project,s.scene].filter(Boolean).join(' / ')||'Tutti gli output';this.imageTab.classList.toggle('active',s.mode==='image');this.videoTab.classList.toggle('active',s.mode==='video');this.editRow.hidden=s.mode==='video';let n=0;try{n=plannedJobs(s).length;}catch{}this.runLabel.textContent=this.busy?'Invio…':`Run${n?' / '+n:''}`;this.runButton.disabled=this.busy||!n;this.runButton.title=`${n} generazioni API indipendenti, in parallelo`;}
 switchMode(mode){this.state.mode=mode;this.save();this.renderControls();this.updateHeader();this.refreshPrices();}
 toggle(label,checked,onchange){const b=btn('',()=>{checked=!checked;b.classList.toggle('on',checked);b.setAttribute('aria-checked',String(checked));onchange(checked);},'dap-toggle'+(checked?' on':''),label);b.setAttribute('role','switch');b.setAttribute('aria-checked',String(checked));const knob=el('span','','dap-toggle-knob');knob.append(icon('lines'));b.append(knob);return b;}
 field(parent,name,value,onchange,opts={}){
  const row=el('label','','dap-field');row.append(el('span',name));let input;
  if(opts.choices){input=el('select');for(const choice of [...new Set([String(value),...opts.choices])]){const o=el('option',choice);o.value=choice;input.append(o);}input.value=String(value);row.classList.add('has-select');}
  else{input=el('input');input.type=opts.type||'text';if(input.type==='checkbox')input.checked=!!value;else input.value=String(value??'');}
  input.setAttribute('aria-label',name);if(opts.min!==undefined)input.min=String(opts.min);if(opts.max!==undefined)input.max=String(opts.max);if(opts.step!==undefined)input.step=String(opts.step);if(opts.placeholder)input.placeholder=opts.placeholder;if(opts.readonly)input.readOnly=true;
  input.onchange=()=>onchange(input.type==='checkbox'?input.checked:input.value);row.append(input);
  if(input.tagName==='INPUT'&&['text','number','color'].includes(input.type)&&!opts.readonly)input.oninput=()=>input.onchange();
  if(!opts.readonly&&(opts.choices||opts.type==='number')){
   const step=direction=>{if(opts.choices){input.selectedIndex=(input.selectedIndex+direction+input.options.length)%input.options.length;}else{const next=Number(input.value||0)+direction*Number(opts.step||1);input.value=String(Math.min(opts.max??Infinity,Math.max(opts.min??-Infinity,next)));}input.onchange();};
   const previous=ib('arrow','Riduci / precedente '+name,e=>step(-1),'dap-field-step'),next=ib('arrow','Aumenta / successivo '+name,e=>step(1),'dap-field-step next');
   previous.addEventListener('click',e=>e.preventDefault());next.addEventListener('click',e=>e.preventDefault());row.prepend(previous);row.append(next);
  }
  parent.append(row);return input;
 }
 renderControls(){
  const c=this.controls,s=this.state;c.replaceChildren();
  const refs=el('section','','dap-section');refs.append(el('div','REFERENCES','dap-label'));this.refs=el('div','','dap-refs');refs.append(this.refs);this.renderRefs();
  const prompt=el('section','','dap-section dap-prompt');prompt.append(el('div','PROMPT','dap-label'));const wrap=el('div','','dap-prompt-wrap'),area=el('textarea');area.value=s.prompts[s.mode]||'';area.setAttribute('aria-label','Prompt');area.placeholder='Scrivi il prompt…';area.oninput=()=>{s.prompts[s.mode]=area.value;this.save();};
  const resize=el('div','','dap-resize-handle');resize.title='Trascina per ingrandire il prompt';let start=null;
  resize.onpointerdown=e=>{e.preventDefault();start={y:e.clientY,height:area.offsetHeight};resize.setPointerCapture(e.pointerId);};resize.onpointermove=e=>{if(start)area.style.height=Math.max(90,start.height+e.clientY-start.y)+'px';};resize.onpointerup=resize.onpointercancel=()=>start=null;wrap.append(area,resize);prompt.append(wrap);
  const work=el('section','','dap-section dap-work');work.append(el('div','FILENAME / WORKSPACE','dap-label'));
  this.field(work,'FILENAME',s.filename,v=>{s.filename=v;this.save();this.namePreview.textContent=this.filenamePreview();},{placeholder:'DOGMA'});
  this.field(work,'PROJECT',s.project,v=>{s.project=v;this.save();this.updateHeader();this.namePreview.textContent=this.filenamePreview();},{placeholder:'Facoltativo'});
  this.field(work,'SCENE',s.scene,v=>{s.scene=v;this.save();this.updateHeader();this.namePreview.textContent=this.filenamePreview();},{placeholder:'Facoltativo'});
  const date=el('div','','dap-date-row'),datePicker=el('input');datePicker.type='date';const code=s.date||todayCode();datePicker.value=`20${code.slice(4,6)}-${code.slice(2,4)}-${code.slice(0,2)}`;datePicker.setAttribute('aria-label','Data del filename');datePicker.onchange=()=>{const [year,month,day]=datePicker.value.split('-');if(!year)return;s.date=day+month+year.slice(-2);s.dateMode='manual';this.save();this.namePreview.textContent=this.filenamePreview();};date.append(this.toggle('Aggiungi data al filename',s.appendDate,v=>{s.appendDate=v;s.date ||= todayCode();this.save();this.namePreview.textContent=this.filenamePreview();}),el('span','Aggiungi data'),datePicker);work.append(date);
  const choose=ib('folder','Scegli cartella di lavoro',()=>this.chooseWorkspace(),'dap-workspace-button');choose.append(el('span',s.workspace||'Scegli cartella di lavoro'));work.append(choose);
  this.namePreview=el('div',this.filenamePreview(),'dap-filename-preview');work.append(this.namePreview);
  const models=el('section','','dap-section dap-models');models.append(el('div','MODELS','dap-label'));for(const f of families(s))models.append(this.model(f));
  c.append(refs,prompt,work,models);
 }
 filenamePreview(){return [...titleParts(this.state),'MODEL',this.state.mode==='video'?'00001.mp4':'00001.png'].filter(Boolean).join('_');}
 renderRefs(){
  if(!this.refs)return;this.refs.replaceChildren();
  const visible=this.state.references.filter(r=>!r.modes||r.modes.includes(this.state.mode));
  visible.forEach((r,i)=>{
   const tile=el('article','','dap-ref');tile.classList.toggle('disabled',!r.enabled);tile.dataset.ref=String(i);
   const media=el(r.kind==='video'?'video':'img');media.src=r.processedPreview?this.bridge.view(r.processedPreview):r.preview||this.bridge.view(r.file);media.draggable=false;if(r.kind==='video'){media.muted=true;media.preload='metadata';media.onpointerenter=()=>media.play().catch(()=>{});media.onpointerleave=()=>media.pause();}else media.alt=`Image ${i+1}`;
   media.onclick=()=>r.kind==='video'?this.referenceVideo(r):referenceEditor(this,r);
   media.onerror=()=>tile.classList.add('missing');
   const tools=el('div','','dap-ref-tools');tools.append(this.toggle(`Attiva reference ${i+1}`,r.enabled,v=>{r.enabled=v;this.save();this.renderRefs();this.refreshPrices();}));
   if(r.kind==='image')tools.append(ib('edit',`Modifica reference ${i+1}`,()=>referenceEditor(this,r)));
   else tools.append(ib('play',`Apri video reference ${i+1}`,()=>this.referenceVideo(r)));
   if(i>0)tools.append(ib('arrow',`Sposta prima reference ${i+1}`,()=>{const a=this.state.references.indexOf(visible[i-1]),b=this.state.references.indexOf(r);[this.state.references[a],this.state.references[b]]=[r,visible[i-1]];this.save();this.renderRefs();}));
   tools.append(ib('close',`Rimuovi reference ${i+1}`,()=>{this.state.references.splice(this.state.references.indexOf(r),1);this.save();this.renderRefs();this.refreshPrices();}));
   tile.append(media,el('span',`${String(i+1).padStart(2,'0')} / ${r.kind==='video'?'VIDEO':'IMAGE'}`,'dap-ref-order'),tools);
   if(r.process?.enabled)tile.append(el('span','EDIT','dap-ref-edited'));
   if(this.state.mode==='video'&&r.kind==='image'){
    const select=el('select','','dap-ref-role');select.setAttribute('aria-label',`Ruolo reference ${i+1}`);for(const [key,text] of [['reference','Reference'],['first','First frame'],['last','Last frame']]){const o=el('option',text);o.value=key;select.append(o);}select.value=r.role||'reference';select.onchange=()=>{r.role=select.value;this.save();};tile.append(select);
   }
   this.refs.append(tile);
  });
  const add=ib('plus','Aggiungi immagini o video',()=>this.pickReferences(),'dap-add');add.append(el('span','Immagini / Video'));this.refs.append(add);
 }
 pickReferences(replace=null){const i=el('input');i.type='file';i.accept='image/*,video/*';i.multiple=!replace;i.hidden=true;this.root.append(i);i.onchange=()=>{this.addReferences([...i.files],replace);i.remove();};i.addEventListener('cancel',()=>i.remove(),{once:true});i.click();}
 async addReferences(files,replace=null){try{this.note('Caricamento reference…');for(const file of files){if(!/^(image|video)\//.test(file.type))throw new Error('Scegli immagini o video.');const uploaded=await this.bridge.upload(file);if(this.closed)return;const r={...uploaded,enabled:true,modes:[this.state.mode],role:'reference',process:{enabled:false,mask:false,maskMode:'isolate',source:'paint',flip:false,invert:false,crop:false,fillHoles:true,expand:0,blur:0,targetWidth:0,targetHeight:0,background:'#00ff00'}};if(replace){const at=this.state.references.indexOf(replace);this.state.references.splice(at,1,r);}else this.state.references.push(r);}this.save();this.renderRefs();this.refreshPrices();this.note('Reference aggiornate. L’ordine è quello mostrato.');}catch(e){this.note(e.message,true);}}
 referenceVideo(ref){openViewer(this,{job:{kind:'video',label:ref.file,study:true},file:{url:ref.preview||this.bridge.view(ref.file)},index:0});}
 model(f){
  const m=this.state.models[f.key],wrap=el('div','','dap-model'),row=el('div','','dap-model-head');wrap.setAttribute('role','group');wrap.setAttribute('aria-label',f.name);
  const toggle=this.toggle(`Attiva ${f.name}`,m.enabled,v=>{m.enabled=v;wrap.classList.toggle('enabled',v);this.save();this.updateHeader();});wrap.classList.toggle('enabled',m.enabled);
  const details=el('details');details.open=!!m.expanded;details.ontoggle=()=>{m.expanded=details.open;this.save();};
  const summary=el('summary');this.priceLabels ||= new Map();const price=el('small','— CREDITS / '+(f.key==='seedance'?'RUN':'IMAGE'));this.priceLabels.set(f.key,price);summary.append(el('span',f.name),price,icon('chevron'));details.append(summary);
  const body=el('div','','dap-model-body');
  this.field(body,'QUANTITY',m.quantity,v=>{m.quantity=Number(v);this.save();this.updateHeader();},{type:'number',min:1,max:64});
  body.append(el('div','Richieste in parallelo · Seed diversi','dap-field-hint'));
  if(f.key==='seedance')this.field(body,'WORKFLOW',m.engine,v=>{m.engine=v;this.save();wrap.replaceWith(this.model(f));this.refreshPrices();},{choices:['reference','frames']});
  const values=m.engine==='frames'?m.frames:m.parameters;
  for(const [key,value] of Object.entries(values)){
   if(['prompt','model.prompt','system_prompt','seed','model.seed','n'].includes(key)||key.startsWith('control_after_generate')||key.endsWith('asset_id'))continue;
   const opts={};if(enumValues[key])opts.choices=enumValues[key];
   if(key==='model'){if(f.key==='nano')opts.choices=['gemini-3-pro-image-preview','Nano Banana 2 (Gemini 3.1 Flash Image)'];else opts.readonly=true;}
   if(key==='resolution'&&f.key==='flux')opts.choices=['0.75K','1K','1.5K','2K','4K'];
   if(typeof value==='boolean')opts.type='checkbox';if(typeof value==='number'){opts.type='number';opts.min=key==='model.duration'?4:0;opts.max=key==='model.duration'?30:8594;}
   const spec=this.bridge.inputSpec?.(this.state,f,key);
   if(spec){const info=spec[1]||{};if(Array.isArray(spec[0]))opts.choices=spec[0];else if(spec[0]==='COMBO')opts.choices=info.options;if(info.min!==undefined)opts.min=info.min;if(info.max!==undefined)opts.max=info.max;if(info.step!==undefined)opts.step=info.step;}
   this.field(body,displayName(key),value,v=>{values[key]=typeof value==='boolean'?v:typeof value==='number'?Number(v):v;this.save();this.refreshPrices();},opts);
  }
  if(values.system_prompt!==undefined){const advanced=el('details','','dap-advanced');advanced.append(el('summary','SYSTEM PROMPT'));const text=el('textarea');text.value=values.system_prompt;text.setAttribute('aria-label',f.name+' system prompt');text.oninput=()=>{values.system_prompt=text.value;this.save();};advanced.append(text);body.append(advanced);}
  if(f.key==='seedance')body.append(el('div','Reference: genera, modifica o estende un video. Frames: usa i ruoli First / Last delle reference. In Edit la durata segue il video sorgente.','dap-field-hint'));
  details.append(body);row.append(toggle,details);wrap.append(row);return wrap;
 }
 async refreshCredits(){if(this.creditBusy||this.closed)return;this.creditBusy=true;try{const result=await this.bridge.credits();if(!this.closed){this.credit.textContent=result.text;this.credit.title=result.title;}}catch{}finally{this.creditBusy=false;}}
 refreshPrices(){if(this.closed)return;for(const f of families(this.state)){const text=this.bridge.price?.(this.state,f);const node=this.priceLabels?.get(f.key);if(node&&text){node.textContent=text;node.title='Stima calcolata dalle stesse regole di Comfy per questi parametri';}}}
 allResults(){const map=new Map;for(const r of [...this.library,...this.state.results])map.set(r.id,r);return [...map.values()].sort((a,b)=>(b.started||b.finished||0)-(a.started||a.finished||0));}
 renderFilters(){
  if(!this.filters)return;const s=this.state,all=this.allResults();this.filters.replaceChildren();
  const model=el('details','','dap-filter-models');const summary=el('summary');summary.append(icon('filter'),el('span',s.filters.models.length?s.filters.models.map(k=>ALL_FAMILIES.find(f=>f.key===k)?.name||k).join(', '):'Tutti i modelli'),icon('chevron'));const menu=el('div','','dap-filter-menu');
  const any=btn('Tutti i modelli',()=>{s.filters.models=[];this.save();this.renderFilters();this.renderGallery();});menu.append(any);
  for(const f of ALL_FAMILIES){const item=el('label'),check=el('input');check.type='checkbox';check.checked=s.filters.models.includes(f.key);check.onchange=()=>{s.filters.models=check.checked?[...s.filters.models,f.key]:s.filters.models.filter(k=>k!==f.key);this.save();this.renderGallery();summary.querySelector('span').textContent=s.filters.models.length?s.filters.models.map(k=>ALL_FAMILIES.find(f=>f.key===k)?.name).join(', '):'Tutti i modelli';};item.append(check,el('span',f.name));menu.append(item);}model.append(summary,menu);this.filters.append(model);
  const select=(name,current,choices,change)=>{const box=el('label','','dap-filter');box.append(el('span',name));const input=el('select');input.setAttribute('aria-label',name);for(const [value,text] of choices){const option=el('option',text);option.value=value;input.append(option);}input.value=current;input.onchange=()=>{change(input.value);this.save();this.renderFilters();this.renderGallery();};box.append(input,icon('chevron'));this.filters.append(box);};
  const projects=[...new Set(all.map(r=>r.project||''))].sort();select('Progetto',s.filters.project,[['*','Tutti i progetti'],...projects.map(p=>[p,p||'Senza progetto'])],v=>{s.filters.project=v;s.filters.scene='*';});
  const scenes=[...new Set(all.filter(r=>s.filters.project==='*'||(r.project||'')===s.filters.project).map(r=>r.scene||''))].sort();select('Scena',s.filters.scene,[['*','Tutte le scene'],...scenes.map(v=>[v,v||'Senza scena'])],v=>s.filters.scene=v);
  select('Output',s.filters.kind,[['all','Immagini e video'],['image','Immagini'],['video','Video']],v=>s.filters.kind=v);
  const ws=[...new Set(all.map(r=>r.workspace||''))];if(ws.length>1)select('Cartella',s.filters.workspace,[['*','Tutte le cartelle'],...ws.map(v=>[v,v.split(/[\\/]/).filter(Boolean).at(-1)||'Comfy output'])],v=>s.filters.workspace=v);
  this.filters.append(ib('refresh','Aggiorna libreria',()=>this.refreshLibrary()));
 }
 renderGallery(){
  const scroll=this.galleryViewport?.scrollTop||0;this.gallery.replaceChildren();this.cards.clear();const list=filterResults(this.allResults(),this.state.filters);
  if(!list.length){const empty=el('div','','dap-empty');empty.append(el('span','DOGMA / OUTPUT'),el('h2',this.allResults().length?'Nessun risultato con questi filtri.':'Pronto per il prossimo frame.'),el('p',this.allResults().length?'Cambia progetto, scena o modelli per vedere gli altri output.':'Scegli i modelli e la quantità. Run avvia le richieste API in parallelo.'));this.gallery.append(empty);return;}
  for(const job of list){const files=job.images?.length?job.images:[null];files.forEach((file,i)=>this.gallery.append(this.card(job,file,i)));}
  this.updateCards();this.galleryViewport.scrollTop=scroll;this.applyDensity();
 }
 card(job,file,index){
  const card=el('article','','dap-card');card.dataset.job=job.id;const f=ALL_FAMILIES.find(f=>f.key===job.family),title=job.label||f?.name||'Output';
  if(file){
   const media=el('div','','dap-card-media');
   if(job.kind==='video'){const video=el('video');video.src=this.bridge.view(file);video.muted=true;video.preload='metadata';video.loop=true;media.append(video);media.onpointerenter=()=>video.play().catch(()=>{});media.onpointerleave=()=>video.pause();media.append(icon('play'));}
   else{const base=job.imageEdit&&job.baseReference?(job.baseReference.comparePreview||this.bridge.view(job.baseReference.processedPreview||job.baseReference.file)):null;const comparison=hoverCompare(media,this.bridge.view(file),base);comparison.image.loading='lazy';comparison.image.alt=title;}
   media.onclick=()=>openViewer(this,{job,file,index});media.tabIndex=0;media.setAttribute('role','button');media.setAttribute('aria-label','Apri '+title);media.onkeydown=e=>{if(e.key==='Enter')media.click();};card.append(media);
   const tools=el('div','','dap-card-tools'),item={id:job.id+':'+index,job,file,index};
   const select=ib('compare','Seleziona per confronto A/B',()=>{const at=this.selection.findIndex(x=>x.id===item.id);if(at>=0){this.selection.splice(at,1);select.classList.remove('selected');}else if(this.selection.length<2){this.selection.push(item);select.classList.add('selected');}this.ab.classList.toggle('active',this.selection.length===2);this.note(`${this.selection.length}/2 risultati selezionati per A/B.`);});
   tools.append(select,ib('plus','Usa come reference',()=>this.reuse(file,job.kind)),ib('download','Scarica file',()=>this.downloadImage(file)));card.append(tools);
   if(job.study)card.append(el('span','DESIGN REFERENCE','dap-study'));
  }else{card.classList.add('pending');card.append(el('div','','dap-spinner'),el('span','','dap-job-state'));}
  const footer=el('footer','','dap-card-footer');footer.append(el('span',title+(job.index!==undefined?' / '+(job.index+1):'')),el('span','','dap-elapsed'));card.append(footer);
  const tags=[job.project,job.scene].filter(Boolean);if(tags.length)card.append(el('div',tags.join(' / '),'dap-card-tags'));
  if(job.warning||job.error)card.append(el('p',job.warning||job.error,'dap-card-error'));
  if(!this.cards.has(job.id))this.cards.set(job.id,[]);this.cards.get(job.id).push(card);return card;
 }
 updateCards(){for(const job of this.allResults())for(const card of this.cards.get(job.id)||[]){const status=card.querySelector('.dap-job-state');if(status)status.textContent=({submitting:'Invio',queued:'In attesa di Comfy',running:'Generazione API',failed:'Errore',cancelled:'Interrotta'})[job.status]||job.status;card.classList.toggle('stopped',terminal.has(job.status));const elapsed=card.querySelector('.dap-elapsed');elapsed.textContent=job.study?'LAYOUT':job.started?Math.floor(((job.finished||Date.now())-job.started)/1000)+'s':'';if(job.error&&!card.querySelector('.dap-card-error'))card.append(el('p',job.error,'dap-card-error'));}}
 modalBox(title,cls=''){
  this.modal?.close();const dialog=this.modal=el('dialog','','dap-modal '+cls);dialog.setAttribute('aria-label',title);const header=el('header');header.append(el('span',title),ib('close','Chiudi',()=>dialog.close()));dialog.append(header);this.root.append(dialog);
  let down=false;dialog.addEventListener('pointerdown',e=>down=e.target===dialog);dialog.addEventListener('click',e=>{if(down&&e.target===dialog)dialog.close();down=false;});
  dialog.addEventListener('cancel',e=>e.stopPropagation());dialog.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();dialog.close();}});dialog.addEventListener('close',()=>{dialog.remove();if(this.modal===dialog)this.modal=null;});dialog.tabIndex=-1;dialog.showModal();dialog.focus({preventScroll:true});return dialog;
 }
 compare(){if(this.selection.length!==2){this.note('Seleziona due immagini con il bottone A/B sulle miniature.');return;}if(this.selection.some(x=>x.job.kind==='video')){this.note('Il confronto A/B è disponibile per le immagini.');return;}openViewer(this,this.selection[0],this.selection[1]);}
 async openOutput(job,index){try{await this.bridge.openOutput(job.id,index);}catch(e){this.note(e.message,true);if(this.modal){let note=this.modal.querySelector('.dap-operation-note');if(!note){note=el('p','','dap-operation-note');this.modal.append(note);}note.textContent=e.message;}}}
 async downloadImage(file){try{const r=await fetch(this.bridge.view(file));if(!r.ok)throw new Error('File non disponibile.');const url=URL.createObjectURL(await r.blob());this.urls.add(url);const a=el('a');a.href=url;a.download=file.filename||'DOGMA_output';a.click();}catch(e){this.note(e.message,true);}}
 async reuse(file,kind){try{const r=await fetch(this.bridge.view(file));if(!r.ok)throw new Error('File non disponibile.');const blob=await r.blob();await this.addReferences([new File([blob],file.filename||'DOGMA_reference.png',{type:blob.type|| (kind==='video'?'video/mp4':'image/png')})]);}catch(e){this.note(e.message,true);}}
 async chooseWorkspace(){
  try{const chosen=await this.bridge.chooseFolder(this.state.workspace);if(chosen.cancelled)return;if(chosen.path){this.state.workspace=chosen.path;this.save();this.renderControls();this.note('Cartella di lavoro selezionata.');return;}if(chosen.browse)await this.folderBrowser();}catch(e){this.note(e.message,true);}
 }
 async folderBrowser(){const box=this.modalBox('CARTELLA DI LAVORO'),list=el('div','','dap-folder-list');box.append(list);const render=async path=>{try{const data=await this.bridge.folders(path);list.replaceChildren(el('div',data.path,'dap-folder-path'));if(data.parent)list.append(btn('↑ Cartella superiore',()=>render(data.parent),'dap-outline'));for(const dir of data.directories){const b=ib('folder',dir.name,()=>render(dir.path));b.append(el('span',dir.name));list.append(b);}list.append(btn('Usa questa cartella',async()=>{try{const result=await this.bridge.workspace(data.path);this.state.workspace=result.path;this.save();box.close();this.renderControls();}catch(e){this.note(e.message,true);}},'dap-outline'));}catch(e){list.replaceChildren(el('p',e.message));}};await render(this.state.workspace);}
 async refreshLibrary(){if(!this.bridge.library||this.closed)return;try{this.library=await this.bridge.library();if(this.closed)return;this.renderFilters();this.renderGallery();}catch(e){this.note('Libreria temporaneamente non disponibile.',true);}}
 async run(){
  if(this.busy)return;try{validateState(this.state);}catch(e){this.note(e.message,true);return;}
  this.busy=true;this.updateHeader();const snapshot=copy(this.state),batch=crypto.randomUUID(),started=Date.now();
  const jobs=plannedJobs(snapshot).map(p=>({...p,id:crypto.randomUUID(),batch,started,status:'submitting',images:[]}));
  try{
   const primary=activeReferences(snapshot).find(r=>r.kind==='image');
   if(snapshot.mode==='image'&&snapshot.imageEdit&&primary?.process?.enabled&&primary.process.source!=='prompt'){
    this.note('Preparazione Image 1 per il confronto…');const prepared=await this.bridge.previewReference(primary,primary.process);primary.processedPreview=prepared.file;
   }
   const seed=new Uint32Array(1);crypto.getRandomValues(seed);const compiled=compileBatch(snapshot,jobs,seed[0]%2147483647);
   this.note('Controllo reference e nodi…');await this.bridge.check(snapshot,compiled);if(this.closed)return;
   this.state.results.push(...jobs);this.save();this.renderFilters();this.renderGallery();this.galleryViewport.scrollTop=0;
   const promptId=await this.bridge.queue(compiled,batch,this.state);for(const job of jobs){job.promptId=promptId;if(job.status==='submitting')job.status='queued';}this.save();this.updateCards();this.note(`${jobs.length} generazioni indipendenti inviate in un unico batch parallelo.`);
  }catch(e){for(const j of jobs){if(!terminal.has(j.status)){j.status='failed';j.error=e.message;j.finished=Date.now();}}this.save();this.updateCards();this.note(e.message,true);}finally{this.busy=false;if(!this.closed)this.updateHeader();}
 }
 event(name,d){
  if(!d?.prompt_id)return;const jobs=this.state.results.filter(j=>j.promptId===d.prompt_id);if(!jobs.length)return;
  if(name==='executing'&&d.node){const j=jobs.find(x=>x.generator===String(d.node));if(j)j.status='running';}
  if(name==='executed'){
   const job=jobs.find(x=>x.output===String(d.node));if(job&&d.output?.images){const record=d.output.dogma_records?.[0];Object.assign(job,record||{images:d.output.images,status:'completed',finished:Date.now()});this.renderFilters();this.renderGallery();}
  }
  if(name==='execution_error'){const failed=jobs.find(j=>j.generator===String(d.node_id)||j.output===String(d.node_id));for(const job of jobs)if(!terminal.has(job.status)){job.status=job===failed?'failed':'cancelled';job.error=job===failed?d.exception_message:'Batch arrestato da Comfy. Nessun retry automatico.';job.finished=Date.now();}this.note(d.exception_message||'Errore nel batch.',true);}
  if(name==='execution_interrupted')for(const job of jobs)if(!terminal.has(job.status)){job.status='cancelled';job.finished=Date.now();}
  if(name==='execution_success'){this.recover();this.refreshCredits();this.refreshLibrary();}this.save();this.updateCards();
 }
 async recover(){
  if(this.recovering||!this.bridge.history||this.closed)return;this.recovering=true;
  try{const history=await this.bridge.history();if(this.closed)return;let changed=false;
   for(const record of Object.values(history||{})){
    const meta=record.prompt?.[3]?.extra_pnginfo?.workflow?.extra?.dogma_api_batch;if(meta?.session!==this.state.session)continue;
    for(const saved of meta.jobs){let job=this.state.results.find(x=>x.id===saved.id);if(!job){job=copy(saved);this.state.results.push(job);changed=true;}job.promptId=record.prompt[1];const ui=record.outputs?.[job.output];if(ui?.images?.length){const result=ui.dogma_records?.[0]||{images:ui.images,status:'completed',finished:Date.now()};if(JSON.stringify(job.images)!==JSON.stringify(result.images))changed=true;Object.assign(job,result);}else if(record.status?.completed&&!terminal.has(job.status)){job.status=record.status.status_str==='success'?'missing':'failed';job.finished=Date.now();job.error='Comfy non ha restituito questo output.';}}
   }
   this.save();if(changed){this.renderFilters();this.renderGallery();}else this.updateCards();
  }catch{this.note('La cronologia non è momentaneamente disponibile. I batch già accettati continuano in Comfy.',true);}finally{this.recovering=false;}
 }
}
