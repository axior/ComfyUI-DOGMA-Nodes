import {ALL_FAMILIES,copy,families,orderedFamilies,plannedJobs,compileBatch,validateState,titleParts,todayCode,filterResults,migrateState,activeReferences,visibleReferences,choicesFor,sortedChoices,safeName,orderResults,savedFilename,preparedMask} from './dogma_api_core.js?v=1.0.61';
import {icon} from './dogma_api_icons.js?v=1.0.57';
import {hoverCompare,openViewer} from './dogma_api_viewer.js?v=1.0.60';
import {modelReorder} from './dogma_api_model_order.js?v=1.0.61';
import {referenceEditor} from './dogma_api_reference_editor.js?v=1.0.57';

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
  this.ready=false;
  this.root=el('dialog','','dap');this.root.setAttribute('aria-label','DOGMA API Platform');
  this.root.addEventListener('cancel',e=>{e.preventDefault();this.close();});
  this.root.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});
  this.root.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files.length)this.addReferences([...e.dataTransfer.files]);});
  document.body.append(this.root);this.build();this.root.tabIndex=-1;this.root.showModal();this.root.focus({preventScroll:true});
  this.unsubscribe=this.bridge.subscribe?.((name,d)=>this.event(name,d));
  this.note('Apertura · Collegamento a Comfy…');
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(this.closed)return;this.renderControls();this.renderFilters();this.renderGallery();
  try{await this.bridge.initialize?.(this.state);if(this.closed)return;this.ready=true;this.renderControls();this.updateHeader();this.refreshPrices();this.note(this.bridge.preview?'ANTEPRIMA · Nessuna richiesta API':'Pronto.');}catch(e){this.note('Collegamento non riuscito: '+e.message,true);}
  Promise.allSettled([this.recover(),this.refreshLibrary(),this.refreshCredits()]);
  this.timer=setInterval(()=>{this.updateCards();this.refreshPrices();if(this.state.results.some(r=>!terminal.has(r.status)))this.recover();},500);
  this.creditTimer=setInterval(()=>this.refreshCredits(),30000);
 }
 close(){if(this.closed)return;this.save();this.closed=true;clearInterval(this.timer);clearInterval(this.creditTimer);this.unsubscribe?.();for(const modal of [...(this.modals||[])].reverse())modal.close();this.root.close();this.root.remove();for(const u of this.urls)URL.revokeObjectURL(u);this.bridge.close?.();}
 note(text,bad=false){if(!this.notice)return;this.notice.textContent=text;this.notice.classList.toggle('is-error',bad);}
 build(){
  const header=el('header','','dap-header'),brand=el('div','','dap-brand'),logo=el('img');logo.src=this.bridge.logo();logo.alt='DOGMA';brand.append(logo,el('span','API Platform'));
  const actions=el('div','','dap-actions');this.credit=btn('CREDITS —',()=>this.refreshCredits(),'dap-credit','Aggiorna crediti');
  this.runButton=btn('',()=>this.run(),'dap-run','Avvia generazioni in parallelo');this.runLabel=el('span','Run');this.runButton.append(this.runLabel,icon('play'));
  const runGroup=el('div','','dap-run-group'),counter=el('div','','dap-run-counter'),arrows=el('div');this.runCount=el('input');this.runCount.type='number';this.runCount.min='1';this.runCount.max='64';this.runCount.value=String(this.state.runCount||1);this.runCount.setAttribute('aria-label','Ripetizioni Run');
  const setCount=value=>{const n=Number(value);this.state.runCount=Number.isFinite(n)?Math.max(1,Math.min(64,Math.round(n))):1;this.runCount.value=String(this.state.runCount);this.save();this.updateHeader();};
  this.runCount.oninput=()=>{if(this.runCount.value!=='')setCount(this.runCount.value);};this.runCount.onchange=()=>setCount(this.runCount.value);arrows.append(ib('chevron','Aumenta ripetizioni',()=>setCount(this.state.runCount+1),'dap-run-up'),ib('chevron','Riduci ripetizioni',()=>setCount(this.state.runCount-1)));counter.append(this.runCount,arrows);runGroup.append(counter,this.runButton);
  this.stopButton=btn('■ Stop',()=>this.stop(),'dap-stop','Ferma le generazioni DOGMA');this.stopButton.disabled=true;
  actions.append(this.stopButton,this.credit,ib('download','Salva sessione e workflow',()=>this.bridge.download(this.state)),ib('close','Torna a Comfy',()=>this.close()),runGroup);header.append(brand,actions);
  const layout=el('div','','dap-layout');this.side=el('aside','','dap-side');const tabs=el('nav','','dap-tabs');
  this.imageTab=btn('',()=>this.switchMode('image'),'','Image');this.imageTab.append(icon('image'),el('span','Image'));this.videoTab=btn('',()=>this.switchMode('video'),'','Video');this.videoTab.append(icon('video'),el('span','Video'));tabs.append(this.imageTab,this.videoTab);
  this.editRow=el('div','','dap-edit-mode');this.editRow.append(this.toggle('Image Edit',this.state.imageEdit,v=>{this.state.imageEdit=v;this.save();}),el('span','Image Edit'),el('small','Image 1 → compare'));
  this.controls=el('div','','dap-controls');this.side.append(tabs,this.editRow,this.controls);
  const main=el('main','','dap-main'),toolbar=el('div','','dap-toolbar');this.context=btn('',()=>this.folderBrowser(false),'dap-project','Apri cartella di lavoro');
  const views=el('div','','dap-views');
  const slider=this.slider=el('input');slider.type='range';slider.min='0';slider.max='100';slider.step='any';slider.value=String(this.state.density);slider.setAttribute('aria-label','Dimensione delle immagini');
  slider.oninput=()=>{this.state.density=Number(slider.value);this.applyDensity();this.save();};
  views.append(ib('single','Una immagine grande',()=>{slider.value='0';slider.oninput();}),slider,ib('grid','Griglia compatta',()=>{slider.value='100';slider.oninput();}));toolbar.append(this.context,views);
  this.filters=el('div','','dap-filters');this.notice=el('div','','dap-notice');this.notice.setAttribute('role','status');
  this.galleryViewport=el('div','','dap-gallery-viewport');this.gallery=el('div','','dap-gallery');this.galleryViewport.append(this.gallery);
  this.totalProgress=el('div','','dap-total-progress');this.totalBar=el('div','','dap-progress-track');this.totalFill=el('i');this.totalBar.append(this.totalFill);this.totalText=el('span');this.totalProgress.append(this.totalBar,this.totalText);this.totalProgress.hidden=true;main.append(toolbar,this.filters,this.notice,this.galleryViewport);layout.append(this.side,main);this.root.append(this.totalProgress,header,layout);
  this.updateHeader();this.applyDensity();
  this.resize=new ResizeObserver(()=>this.applyDensity());this.resize.observe(this.galleryViewport);this.root.addEventListener('close',()=>this.resize.disconnect(),{once:true});
  this.note(this.bridge.preview?'ANTEPRIMA · Immagini dal tuo design · Nessuna richiesta API':'Reference, parametri e cartella pronti.');
 }
 applyDensity(){if(!this.gallery)return;const columns=1+3*Number(this.state.density)/100,width=(this.galleryViewport.clientWidth||1400)/columns;this.gallery.style.setProperty('--card-min',Math.max(170,width-18)+'px');this.slider.title=`Dimensione galleria / ${Math.round(width)} px`;}
 updateHeader(){const s=this.state;this.context.textContent=[s.workspace||this.bridge.catalog?.access?.output_root||'Comfy output / DOGMA / API',safeName(s.project),safeName(s.scene)].filter(Boolean).join(' / ');this.context.title=this.context.textContent;this.imageTab.classList.toggle('active',s.mode==='image');this.videoTab.classList.toggle('active',s.mode==='video');this.editRow.hidden=s.mode==='video';let n=0;try{n=plannedJobs(s).length;}catch{}this.runLabel.textContent=this.busy?'Invio…':'Run';this.runCount.disabled=this.busy;this.runButton.disabled=this.busy||!n||!this.ready;this.updateProgress();this.runButton.title=`Run ×${s.runCount||1} · ${n} generazioni totali, con seed diversi`;this.runButton.setAttribute('aria-label',this.runButton.title);}
 switchMode(mode){this.state.mode=mode;this.save();this.renderControls();this.updateHeader();this.refreshPrices();}
 toggle(label,checked,onchange,tag='label'){const control=el(tag,'','dap-toggle'),input=el('input'),track=el('span','','dap-toggle-track');input.type='checkbox';input.checked=!!checked;input.setAttribute('role','switch');input.setAttribute('aria-label',label);input.onchange=()=>onchange(input.checked);control.title=label;track.setAttribute('aria-hidden','true');track.append(el('span','','dap-toggle-knob'));control.append(input,track);return control;}
 field(parent,name,value,onchange,opts={}){
  const row=el('label','','dap-field');row.append(el('span',name));let input,control;
  if(opts.type==='checkbox'){control=this.toggle(name,value,onchange,'span');input=control.querySelector('input');row.classList.add('has-toggle');}
  else if(opts.choices){input=el('select');for(const choice of [...new Set([...opts.choices.map(String),...(!opts.choices.map(String).includes(String(value))?[String(value)]:[])])]){const o=el('option',choice);o.value=choice;input.append(o);}input.value=String(value);row.classList.add('has-select');}
  else{input=el('input');input.type=opts.type||'text';if(input.type==='checkbox')input.checked=!!value;else input.value=String(value??'');}
  input.setAttribute('aria-label',name);if(opts.min!==undefined)input.min=String(opts.min);if(opts.max!==undefined)input.max=String(opts.max);if(opts.step!==undefined)input.step=String(opts.step);if(opts.placeholder)input.placeholder=opts.placeholder;if(opts.readonly)input.readOnly=true;
  input.onchange=()=>onchange(input.type==='checkbox'?input.checked:input.value);row.append(control||input);
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
  const workSection=el('details','','dap-section dap-work');workSection.open=!!s.workExpanded;workSection.ontoggle=()=>{s.workExpanded=workSection.open;this.save();};const workLabel=el('div','FILENAME / WORKSPACE','dap-label dap-work-label');const workTitle=el('summary');this.namePreview=el('span',this.filenamePreview(),'dap-filename-preview');workTitle.append(this.namePreview,icon('chevron'));const work=el('div');workSection.append(workTitle,work);
  this.field(work,'FILENAME',s.filename,v=>{s.filename=v;this.save();this.namePreview.textContent=this.filenamePreview();},{placeholder:'DOGMA'});
  this.field(work,'PROJECT',s.project,v=>{s.project=v;this.save();this.updateHeader();this.namePreview.textContent=this.filenamePreview();},{placeholder:'Facoltativo'});
  this.field(work,'SCENE',s.scene,v=>{s.scene=v;this.save();this.updateHeader();this.namePreview.textContent=this.filenamePreview();},{placeholder:'Facoltativo'});
  const date=el('div','','dap-date-row'),datePicker=el('input');datePicker.type='date';const code=s.date||todayCode();datePicker.value=`20${code.slice(4,6)}-${code.slice(2,4)}-${code.slice(0,2)}`;datePicker.setAttribute('aria-label','Data del filename');datePicker.onchange=()=>{const [year,month,day]=datePicker.value.split('-');if(!year)return;s.date=day+month+year.slice(-2);s.dateMode='manual';this.save();this.namePreview.textContent=this.filenamePreview();};date.append(this.toggle('Aggiungi data al filename',s.appendDate,v=>{s.appendDate=v;s.date ||= todayCode();this.save();this.namePreview.textContent=this.filenamePreview();}),el('span','Aggiungi data'),datePicker);work.append(date);
  const choose=ib('folder','Scegli cartella di lavoro',()=>this.chooseWorkspace(),'dap-workspace-button');choose.append(el('span',s.workspace||'Scegli cartella di lavoro'));const folderRow=el('div','','dap-workspace-row'),explorer=btn('Esplora file',()=>this.openWorkspaceExplorer(),'dap-workspace-explorer','Apri in Esplora file');explorer.append(icon('external'));folderRow.append(choose,explorer);work.append(folderRow);
  const models=el('section','','dap-section dap-models');models.append(el('div','MODELS','dap-label'));for(const f of orderedFamilies(s))models.append(this.model(f));
  if(models.querySelectorAll('.dap-model').length>1)modelReorder(models,order=>{s.modelOrder=[...order,...(s.modelOrder||[]).filter(key=>!order.includes(key))];this.save();});
  if(s.mode==='video'){const choice=el('section','','dap-video-choice');choice.append(el('div','WORKFLOW VIDEO','dap-label'));for(const [key,label] of [['reference','Ref → Video'],['frames','First / Last frame']]){const b=btn(label,()=>{s.models.seedance.engine=key;this.save();this.renderControls();this.refreshPrices();},key===s.models.seedance.engine?'active':'');choice.append(b);}c.append(choice);}
  if(s.mode==='video'){const fix=el('label','','dap-video-repair');fix.append(this.toggle('Correggi scatti',s.videoRepair,v=>{s.videoRepair=v;this.save();},'span'),el('span','Correggi scatti'));fix.append(el('small','Salva anche una seconda copia · durata e fps originali'));c.append(fix);}
  c.append(refs,prompt,workLabel,workSection,models);
 }
 filenamePreview(){return [...titleParts(this.state),'MODEL',this.state.mode==='video'?'00001.mp4':'00001.png'].filter(Boolean).join('_');}
 renderRefs(){
  if(!this.refs)return;this.refs.replaceChildren();
  const visible=visibleReferences(this.state);
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
   if(this.state.mode==='video'&&this.state.models.seedance.engine==='frames'&&r.kind==='image'){
    const select=el('select','','dap-ref-role');select.setAttribute('aria-label',`Ruolo reference ${i+1}`);for(const [key,text] of [['first','First frame'],['last','Last frame']]){const o=el('option',text);o.value=key;select.append(o);}select.value=r.role||'reference';select.onchange=()=>{r.role=select.value;this.save();};tile.append(select);
   }
   this.refs.append(tile);
  });
  const frames=this.state.mode==='video'&&this.state.models.seedance.engine==='frames',mixed=this.state.mode==='video'&&!frames;const add=ib('plus',mixed?'Aggiungi immagini o video':'Aggiungi immagine',()=>this.pickReferences(),'dap-add');const hoverIcon=icon(mixed?'media':'image');hoverIcon.classList.add('dap-add-hover');add.append(hoverIcon);if(!frames||visible.length<2)this.refs.append(add);
 }
 pickReferences(replace=null){const i=el('input');i.type='file';i.accept=this.state.mode==='video'&&this.state.models.seedance.engine!=='frames'?'image/*,video/*':'image/*';i.multiple=!replace;i.hidden=true;this.root.append(i);i.onchange=()=>{this.addReferences([...i.files],replace);i.remove();};i.addEventListener('cancel',()=>i.remove(),{once:true});i.click();}
 async addReferences(files,replace=null){try{this.note('Caricamento reference…');for(const file of files){if(!/^(image|video)\//.test(file.type))throw new Error('Scegli immagini o video.');const frames=this.state.mode==='video'&&this.state.models.seedance.engine==='frames';if(file.type.startsWith('video/')&&(this.state.mode==='image'||frames))throw new Error('In questa modalità puoi caricare solo immagini.');if(frames&&!replace&&visibleReferences(this.state).length>=2)throw new Error('First / Last frame accetta due immagini.');const uploaded=await this.bridge.upload(file);if(this.closed)return;const r={...uploaded,enabled:true,modes:[this.state.mode],role:frames?(replace?.role|| (visibleReferences(this.state).some(r=>r.role==='first')?'last':'first')):'reference',process:{enabled:false,mask:false,maskMode:'edit',source:'paint',flip:false,invert:false,crop:false,fillHoles:false,expand:0,blur:0,targetWidth:0,targetHeight:0,background:'#ff00ff'}};if(replace){const at=this.state.references.indexOf(replace);this.state.references.splice(at,1,r);}else this.state.references.push(r);}this.save();this.renderRefs();this.refreshPrices();this.note('Reference aggiornate. L’ordine è quello mostrato.');}catch(e){this.note(e.message,true);}}
 referenceVideo(ref){openViewer(this,{job:{kind:'video',label:ref.file,study:true},file:{url:ref.preview||this.bridge.view(ref.file)},index:0});}
 model(f){
  const m=this.state.models[f.key],wrap=el('div','','dap-model'),row=el('div','','dap-model-head');wrap.dataset.modelKey=f.key;wrap.setAttribute('role','group');wrap.setAttribute('aria-label',f.name);
  const toggle=this.toggle(`Attiva ${f.name}`,m.enabled,v=>{m.enabled=v;wrap.classList.toggle('enabled',v);this.save();this.updateHeader();});wrap.classList.toggle('enabled',m.enabled);
  const details=el('details');details.open=!!m.expanded;details.ontoggle=()=>{m.expanded=details.open;this.save();};
  const summary=el('summary');this.priceLabels ||= new Map();const price=el('small','— CREDITS / '+(f.key==='seedance'?'RUN':'IMAGE'));this.priceLabels.set(f.key,price);summary.append(el('span',f.name),price,icon('chevron'));details.append(summary);
  const body=el('div','','dap-model-body');
  this.field(body,'QUANTITY',m.quantity,v=>{m.quantity=Number(v);this.save();this.updateHeader();},{type:'number',min:1,max:64});
  body.append(el('div','Richieste in parallelo · Seed diversi','dap-field-hint'));

  const values=m.engine==='frames'?m.frames:m.parameters;
  const nativeSpecs=this.bridge.parameterSpecs?.(this.state,f);const entries=nativeSpecs&&Object.keys(nativeSpecs).length?Object.keys(nativeSpecs).map(key=>[key,values[key]??nativeSpecs[key][1]?.default??choicesFor(nativeSpecs[key])?.[0]??'']):Object.entries(values);
  for(const [key,value] of entries){
   if(['prompt','model.prompt','system_prompt','seed','model.seed','n'].includes(key)||key.startsWith('control_after_generate')||key.endsWith('asset_id'))continue;
   const opts={};if(enumValues[key])opts.choices=enumValues[key];
   if(key==='model'){if(f.key==='nano')opts.choices=['gemini-3-pro-image-preview','Nano Banana 2 (Gemini 3.1 Flash Image)'];else opts.readonly=true;}
   if(key==='resolution'&&f.key==='flux')opts.choices=['0.75K','1K','1.5K','2K','4K'];
   if(typeof value==='boolean')opts.type='checkbox';if(typeof value==='number'){opts.type='number';opts.min=key==='model.duration'?4:0;opts.max=key==='model.duration'?30:8594;}
   const spec=this.bridge.inputSpec?.(this.state,f,key);
   if(spec){const info=spec[1]||{};if(Array.isArray(spec[0]))opts.choices=spec[0];else if(choicesFor(spec))opts.choices=choicesFor(spec);if(info.min!==undefined)opts.min=info.min;if(info.max!==undefined)opts.max=info.max;if(info.step!==undefined)opts.step=info.step;}
   if(opts.choices){opts.choices=sortedChoices(key,opts.choices);delete opts.readonly;}
   this.field(body,displayName(key),value,v=>{values[key]=typeof value==='boolean'?v:typeof value==='number'?Number(v):v;if(key==='model'){this.bridge.changeModel?.(this.state,f);this.renderControls();}this.save();this.refreshPrices();},opts);
  }
  if(values.system_prompt!==undefined){const advanced=el('details','','dap-advanced');advanced.append(el('summary','SYSTEM PROMPT'));const text=el('textarea');text.value=values.system_prompt;text.setAttribute('aria-label',f.name+' system prompt');text.oninput=()=>{values.system_prompt=text.value;this.save();};advanced.append(text);body.append(advanced);}
  if(f.key==='seedance')body.append(el('div',m.engine==='frames'?'Usa un First frame, un Last frame o entrambi. Sono accettate soltanto immagini.':'Usa immagini o video come reference. In Edit la durata segue il video sorgente.','dap-field-hint'));
  details.append(body);row.append(toggle,details);wrap.append(row);return wrap;
 }
 async refreshCredits(){if(this.creditBusy||this.closed)return;this.creditBusy=true;try{const result=await this.bridge.credits();if(!this.closed){this.credit.textContent=result.text;this.credit.title=result.title;}}catch{}finally{this.creditBusy=false;}}
 refreshPrices(){if(this.closed)return;for(const f of families(this.state)){const text=this.bridge.price?.(this.state,f);const node=this.priceLabels?.get(f.key);if(node&&text){node.textContent=text;node.title='Stima calcolata dalle stesse regole di Comfy per questi parametri';}}}
 allResults(){const map=new Map;for(const r of [...this.library,...this.state.results])map.set(r.id,r);return orderResults([...map.values()]);}
 renderFilters(){
  if(!this.filters)return;const s=this.state,all=this.allResults();this.filters.replaceChildren();
  const model=el('details','','dap-filter-models');const summary=el('summary');summary.append(icon('filter'),el('span',s.filters.models.length?s.filters.models.map(k=>ALL_FAMILIES.find(f=>f.key===k)?.name||k).join(', '):'Tutti i modelli'),icon('chevron'));const menu=el('div','','dap-filter-menu');
  const any=btn('Tutti i modelli',()=>{s.filters.models=[];this.save();this.renderFilters();this.renderGallery();});menu.append(any);
  for(const f of ALL_FAMILIES){const item=el('label'),check=el('input');check.type='checkbox';check.checked=s.filters.models.includes(f.key);check.onchange=()=>{s.filters.models=check.checked?[...s.filters.models,f.key]:s.filters.models.filter(k=>k!==f.key);this.save();this.renderGallery();summary.querySelector('span').textContent=s.filters.models.length?s.filters.models.map(k=>ALL_FAMILIES.find(f=>f.key===k)?.name).join(', '):'Tutti i modelli';};item.append(check,el('span',f.name));menu.append(item);}model.append(summary,menu);this.filters.append(model);
  const select=(name,current,choices,change)=>{const box=el('label','','dap-filter');box.append(el('span',name));const input=el('select');input.setAttribute('aria-label',name);for(const [value,text] of choices){const option=el('option',text);option.value=value;input.append(option);}input.value=current;input.onchange=()=>{change(input.value);this.save();this.renderFilters();this.renderGallery();};input.style.paddingLeft=(name.length*.6+1.8)+'em';box.append(input,icon('chevron'));this.filters.append(box);};
  const projects=[...new Set(all.map(r=>r.project||''))].sort();select('Progetto',s.filters.project,[['*','Tutti i progetti'],...projects.map(p=>[p,p||'Senza progetto'])],v=>{s.filters.project=v;s.filters.scene='*';});
  const scenes=[...new Set(all.filter(r=>s.filters.project==='*'||(r.project||'')===s.filters.project).map(r=>r.scene||''))].sort();select('Scena',s.filters.scene,[['*','Tutte le scene'],...scenes.map(v=>[v,v||'Senza scena'])],v=>s.filters.scene=v);
  select('Output',s.filters.kind,[['all','Immagini e video'],['image','Immagini'],['video','Video']],v=>s.filters.kind=v);
  const ws=[...new Set(all.map(r=>r.workspace||''))];if(ws.length>1)select('Cartella',s.filters.workspace,[['*','Tutte le cartelle'],...ws.map(v=>[v,v.split(/[\\/]/).filter(Boolean).at(-1)||'Comfy output'])],v=>s.filters.workspace=v);
  const errors=el('label','','dap-error-filter');errors.append(this.toggle('Mostra o nascondi generazioni fallite',!s.filters.hideErrors,checked=>{s.filters.hideErrors=!checked;this.save();this.renderGallery();},'span'),el('span','Mostra errori'));this.filters.append(errors,this.compareToggle(),ib('refresh','Aggiorna libreria',()=>this.refreshLibrary()));
 }
 renderGallery(){
  const scroll=this.galleryViewport?.scrollTop||0,version=this.galleryVersion=(this.galleryVersion||0)+1;this.gallery.replaceChildren();this.cards.clear();const list=filterResults(this.allResults(),this.state.filters);
  if(!list.length){const empty=el('div','','dap-empty');empty.append(el('span','DOGMA / OUTPUT'),el('h2',this.allResults().length?'Nessun risultato con questi filtri.':'Pronto per il prossimo frame.'),el('p',this.allResults().length?'Cambia progetto, scena o modelli per vedere gli altri output.':'Scegli i modelli e la quantità. Run avvia le richieste API in parallelo.'));this.gallery.append(empty);return;}
  const pending=list.flatMap(job=>(job.images?.length?job.images:[null]).map((file,index)=>({job,file,index})));let offset=0;
  const append=()=>{if(this.closed||version!==this.galleryVersion)return;const fragment=document.createDocumentFragment();for(const item of pending.slice(offset,offset+40))fragment.append(this.card(item.job,item.file,item.index));this.gallery.append(fragment);offset+=40;this.updateCards();this.updateSelection();if(offset<pending.length)requestAnimationFrame(append);};append();this.galleryViewport.scrollTop=scroll;this.applyDensity();
 }
 card(job,file,index){
  const card=el('article','','dap-card');card.dataset.job=job.id;const f=ALL_FAMILIES.find(f=>f.key===job.family),title=job.label||f?.name||'Output';
  if(file){
   const media=el('div','','dap-card-media');
   if(job.kind==='video'){
    const video=el('video');video.src=this.bridge.view(file);video.muted=true;video.preload='metadata';video.loop=true;video.playsInline=true;media.append(video);
    const duration=el('span','','dap-video-duration');video.onloadedmetadata=()=>{duration.textContent=Number.isFinite(video.duration)?`${Math.floor(video.duration/60)}:${String(Math.floor(video.duration%60)).padStart(2,'0')}`:'';};media.append(icon('playCircle'),duration);
    media.onpointerenter=()=>{video.play().then(()=>media.classList.add('playing')).catch(()=>{});};media.onpointerleave=()=>{video.pause();media.classList.remove('playing');};
   }else{const base=job.imageEdit&&job.baseReference?(job.baseReference.comparePreview||this.bridge.view(job.baseReference.processedPreview||job.baseReference.file)):null;const comparison=hoverCompare(media,this.bridge.view(file),base,()=>this.state.compareEnabled!==false);comparison.image.loading='lazy';comparison.image.decoding='async';comparison.image.alt=title;}
   media.onclick=()=>openViewer(this,{job,file,index});media.tabIndex=0;media.setAttribute('role','button');media.setAttribute('aria-label','Apri '+title);media.onkeydown=e=>{if(e.key==='Enter')media.click();};card.append(media);
   const tools=el('div','','dap-card-tools'),item={id:job.id+':'+index,job,file,index};
   const select=btn('A\\B',()=>this.selectCompare(item),'dap-icon-button dap-ab','Scegli immagine o video per il confronto A/B');select.dataset.compare=item.id;
   tools.append(select,ib('plus','Usa come reference',()=>this.reuse(file,job.kind)),ib('prompt','Leggi e copia prompt',()=>this.showPrompt(job)),ib('download','Scarica file',()=>this.downloadImage(file)));card.append(tools);
   if(job.study)card.append(el('span','DESIGN REFERENCE','dap-study'));
   if(file.variant){const variant=el('span',({original:'ORIGINALE',repaired:'SCATTI CORRETTI',checked:'VERIFICATO · INVARIATO'})[file.variant]||'','dap-video-variant');variant.title=job.repair?.status==='unchanged'?'Nessuno scatto rilevato: copia identica all’originale.':variant.textContent;card.append(variant);}
  }else{
   card.classList.add('pending');const logo=el('video','','dap-loading-logo');logo.src=this.bridge.loadingLogo();logo.muted=true;logo.loop=true;logo.autoplay=true;logo.playsInline=true;logo.setAttribute('aria-label','Generazione in corso');
   const track=el('div','','dap-progress-track dap-card-progress');track.append(el('i'));const error=el('div','','dap-error-content');error.append(el('span','ERRORE'),el('p',job.error||''));card.append(logo,track,error);
  }
  const footer=el('footer','','dap-card-footer'),caption=el('span',title+(job.index!==undefined?' / '+(job.index+1):'')+(file?' - '+savedFilename(job,index):''),'dap-result-name');caption.title=caption.textContent;
  footer.append(caption);if(!file)footer.append(el('span','','dap-job-state'));footer.append(el('span',[job.project,job.scene].filter(Boolean).join(' / '),'dap-card-tags'),el('span','','dap-elapsed'));card.append(footer);
  if(job.warning)card.append(el('p',job.warning,'dap-card-error'));
  card.append(el('span','','dap-error-countdown'));
  if(!this.cards.has(job.id))this.cards.set(job.id,[]);this.cards.get(job.id).push(card);return card;
 }
 updateCards(){
  this.updateProgress();let expired=false;
  for(const job of this.allResults())for(const card of this.cards.get(job.id)||[]){
   const p=this.jobProgress(job),bar=card.querySelector('.dap-card-progress>i');if(bar){bar.style.width=p.percent+'%';bar.parentElement.classList.toggle('indeterminate',!!p.indeterminate);bar.parentElement.title=p.label;}
   const status=card.querySelector('.dap-job-state');if(status)status.textContent=job.status==='repairing'?(job.repairStage||'Correzione scatti'):({submitting:'Invio',queued:'In attesa',running:'Generazione API',failed:'Errore',cancelled:'Interrotta',missing:'Output assente'})[job.status]||job.status;
   card.classList.toggle('stopped',terminal.has(job.status));card.classList.toggle('failed',['failed','missing'].includes(job.status));
   const elapsed=card.querySelector('.dap-elapsed'),seconds=job.started?Math.max(0,Math.floor(((job.finished||Date.now())-job.started)/1000)):null;elapsed.textContent=job.study?'LAYOUT':seconds!==null?seconds+'s'+(!terminal.has(job.status)&&p.expected?'/~'+Math.round(p.expected)+'s':''):'';
   const error=card.querySelector('.dap-error-content p');if(error)error.textContent=job.error||'';
   const countdown=card.querySelector('.dap-error-countdown'),remaining=Math.ceil(((job.errorVisibleUntil||0)-Date.now())/1000);countdown.textContent=this.state.filters.hideErrors&&['failed','missing'].includes(job.status)&&remaining>0?`Si nasconde tra ${remaining}s`:'';
   if(this.state.filters.hideErrors&&['failed','missing'].includes(job.status)&&remaining<=0)expired=true;
   const logo=card.querySelector('.dap-loading-logo');if(logo&&terminal.has(job.status))logo.pause();
  }
  if(expired)this.renderGallery();this.updateSelection();
 }
 selectCompare(item){
  const at=this.selection.findIndex(x=>x.id===item.id);
  if(at>=0)this.selection.splice(at,1);else{if(this.selection.length===2)this.selection=[];this.selection.push(item);}
  this.updateSelection();if(this.selection.length===2){this.note('Confronto A/B · seleziona un’altra immagine per iniziare una nuova coppia.');this.compare();}else this.note(this.selection.length?'A selezionata · scegli il secondo risultato per aprire il confronto.':'Selezione confronto rimossa.');
 }
 updateSelection(){for(const b of this.root?.querySelectorAll('[data-compare]')||[]){const n=this.selection.findIndex(x=>x.id===b.dataset.compare);b.textContent=n<0?'A\\B':n===0?'A':'B';b.classList.toggle('selected',n>=0);b.setAttribute('aria-pressed',String(n>=0));}}
 showPrompt(job){const box=this.modalBox('PROMPT','dap-prompt-modal',true),text=el('textarea');text.value=job.prompt||'Prompt non disponibile per questo output.';text.readOnly=true;text.setAttribute('aria-label','Prompt originale');box.append(text,btn('Copia prompt',async e=>{const button=e.currentTarget;try{await navigator.clipboard.writeText(text.value);button.textContent='Copiato';}catch{text.select();}},'dap-outline'));}
 async openWorkspaceExplorer(){try{const path=this.state.workspace||this.bridge.catalog?.access?.output_root;await this.bridge.explorer(path);}catch(e){this.note(e.message,true);}}
 modalBox(title,cls='',nested=false){
  this.modals ||= [];if(!nested)for(const box of [...this.modals].reverse())box.close();const dialog=this.modal=el('dialog','','dap-modal '+cls);dialog.setAttribute('aria-label',title);const header=el('header');header.append(el('span',title),ib('close','Chiudi',()=>dialog.close()));dialog.append(header);this.root.append(dialog);
  let down=false;dialog.addEventListener('pointerdown',e=>down=e.target===dialog);dialog.addEventListener('click',e=>{if(down&&e.target===dialog)dialog.close();down=false;});
  dialog.addEventListener('cancel',e=>e.stopPropagation());dialog.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();dialog.close();}});dialog.addEventListener('close',()=>{dialog.remove();this.modals=this.modals.filter(d=>d!==dialog);this.modal=this.modals.at(-1)||null;});this.modals.push(dialog);dialog.tabIndex=-1;dialog.showModal();dialog.focus({preventScroll:true});return dialog;
 }
 compareToggle(available=true){
  const label=el('label','','dap-error-filter dap-compare-toggle'),control=this.toggle('Compare',available&&this.state.compareEnabled!==false,v=>this.setCompareEnabled(v),'span');
  const input=control.querySelector('input');input.dataset.compareToggle='';input.disabled=!available;
  label.title=available?'Attiva o disattiva il confronto al passaggio del mouse':'Nessuna immagine di confronto disponibile';
  label.append(control,el('span','Compare'));return label;
 }
 setCompareEnabled(enabled){
  this.state.compareEnabled=!!enabled;this.save();
  for(const input of this.root?.querySelectorAll('[data-compare-toggle]')||[])input.checked=!!enabled&&!input.disabled;
  if(!enabled)for(const host of this.root?.querySelectorAll('.dap-compare-host.comparing')||[])host.classList.remove('comparing');
 }
 compare(){if(this.selection.length===2){this.setCompareEnabled(true);openViewer(this,this.selection[0],this.selection[1]);}}
 async openOutput(job,index){try{const target=await this.bridge.openOutput(job.id,index);await this.folderBrowser(false,target.path,target.filename);}catch(e){this.note(e.message,true);if(this.modal)this.modal.append(el('p',e.message,'dap-operation-note'));}}
 async downloadImage(file){try{const r=await fetch(this.bridge.view(file));if(!r.ok)throw new Error('File non disponibile.');const url=URL.createObjectURL(await r.blob());this.urls.add(url);const a=el('a');a.href=url;a.download=file.filename||'DOGMA_output';a.click();}catch(e){this.note(e.message,true);}}
 async reuse(file,kind){try{const r=await fetch(this.bridge.view(file));if(!r.ok)throw new Error('File non disponibile.');const blob=await r.blob();await this.addReferences([new File([blob],file.filename||'DOGMA_reference.png',{type:blob.type|| (kind==='video'?'video/mp4':'image/png')})]);}catch(e){this.note(e.message,true);}}
 async chooseWorkspace(){return this.folderBrowser(true);}
 async folderBrowser(choose=true,initial=null,selected=''){
  const box=this.modalBox(choose?'SCEGLI CARTELLA DI LAVORO':'CARTELLA / FILE','dap-folder-modal'),bar=el('div','','dap-folder-navigation'),address=el('input'),list=el('div','','dap-folder-list'),footer=el('div','','dap-folder-footer'),error=el('p','','dap-operation-note');address.setAttribute('aria-label','Percorso cartella');bar.append(address);box.append(bar,list,error,footer);
  let navigation=0,typing;const render=async path=>{const token=++navigation;error.textContent='';try{const data=await this.bridge.folders(path);if(!box.isConnected||token!==navigation)return;address.value=data.path;list.replaceChildren();footer.replaceChildren();
   if(data.parent)list.append(btn('↑ Cartella superiore',()=>render(data.parent),'dap-outline'));
   for(const root of data.roots||[]){const b=ib('folder',root.name,()=>render(root.path));b.append(el('span',root.name));list.append(b);}
   for(const dir of data.directories){const b=ib('folder',dir.name,()=>render(dir.path));b.append(el('span',dir.name));list.append(b);}
   for(const file of data.files||[]){const row=el('div',file.name,'dap-folder-file'+(file.name===selected?' selected':''));if(file.name===selected)row.setAttribute('aria-current','true');list.append(row);}
   const name=el('input');name.placeholder='Nome nuova cartella';name.setAttribute('aria-label','Nome nuova cartella');footer.append(name,btn('Crea cartella',async()=>{try{const d=await this.bridge.mkdir(data.path,name.value);await render(d.path);}catch(e){error.textContent=e.message;}},'dap-outline'));
   if(choose)footer.append(btn('Usa questa cartella',async()=>{try{const result=await this.bridge.workspace(data.path);this.state.workspace=result.path;for(const record of result.records||[]){const existing=this.state.results.find(j=>j.id===record.id);if(existing)Object.assign(existing,record);}this.library=[...this.library.filter(r=>!(result.records||[]).some(x=>x.id===r.id)),...(result.records||[])];this.save();this.renderFilters();this.renderGallery();box.close();this.renderControls();this.updateHeader();this.note('Cartella di lavoro selezionata.');}catch(e){error.textContent=e.message;}},'dap-primary'));
   list.querySelector('[aria-current]')?.scrollIntoView({block:'center'});
  }catch(e){if(token===navigation)error.textContent=e.message;}};address.oninput=()=>{clearTimeout(typing);navigation++;typing=setTimeout(()=>render(address.value.trim().replace(/^"|"$/g,'')),650);};address.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(typing);render(address.value.trim().replace(/^"|"$/g,''));}};box.addEventListener('close',()=>{clearTimeout(typing);navigation++;});await render(initial??this.state.workspace);
 }
 jobProgress(job){
  if(terminal.has(job.status))return {percent:job.status==='completed'?100:job.stoppedProgress??Math.min(99,(job.progress||0)*100),label:job.status,remaining:0};
  if(job.status==='repairing')return {percent:Math.min(99,90+9*(job.repairProgress||0)),label:job.repairStage||'Correzione scatti',remaining:null};
  if(Number.isFinite(job.progress)&&job.progress>0)return {percent:Math.min(99,job.progress*100),label:Math.round(job.progress*100)+'% · avanzamento Comfy',remaining:job.progress<1?Math.max(0,Math.round((Date.now()-job.started)/1000*(1-job.progress)/job.progress)):0};
  const samples=this.allResults().filter(j=>j.family===job.family&&j.status==='completed'&&j.finished>j.started&&!j.study).slice(0,8).map(j=>(j.finished-j.started)/1000);
  if(!samples.length)return {percent:15,indeterminate:true,label:'Tempo trascorso · stima disponibile dopo le prime generazioni',remaining:null};
  const expected=samples.reduce((a,b)=>a+b,0)/samples.length,elapsed=(Date.now()-job.started)/1000;
  return {expected,percent:Math.min(94,100*elapsed/expected),remaining:Math.max(0,Math.round(expected-elapsed)),label:elapsed<expected?'~'+Math.round(expected-elapsed)+'s rimanenti · stima':'Finalizzazione · stima superata'};
 }
 updateProgress(){
  if(!this.totalProgress)return;const jobs=this.state.results.filter(j=>!terminal.has(j.status)),ids=new Set(jobs.map(j=>j.batch));const batch=this.state.results.filter(j=>ids.has(j.batch));
  this.stopButton.disabled=!jobs.length&&!this.busy;this.totalProgress.hidden=!jobs.length;if(!jobs.length)return;
  const points=batch.map(j=>this.jobProgress(j));this.totalFill.style.width=points.reduce((s,p)=>s+p.percent,0)/points.length+'%';this.totalBar.classList.toggle('indeterminate',points.some(p=>p.indeterminate));
  const known=jobs.map(j=>this.jobProgress(j).remaining);this.totalText.textContent=`${batch.filter(j=>terminal.has(j.status)).length} / ${batch.length} completate · `+(known.every(n=>n!==null)?`~${Math.max(...known)}s rimanenti · stima`:'Calcolo in corso · tempo residuo non ancora disponibile');
 }
 async stop(){
  this.stopRequested=true;const jobs=this.state.results.filter(j=>!terminal.has(j.status));const ids=[...new Set(jobs.map(j=>j.promptId).filter(Boolean))];this.stopButton.disabled=true;this.note('Interruzione richiesta…');
  const results=await Promise.allSettled(ids.map(id=>this.bridge.cancel(id)));for(let i=0;i<ids.length;i++)if(results[i].status==='fulfilled')for(const job of jobs.filter(j=>j.promptId===ids[i]))if(!terminal.has(job.status)){job.stoppedProgress=this.jobProgress(job).percent;job.status='cancelled';job.finished=Date.now();}
  this.save();this.updateCards();this.note(results.some(r=>r.status==='rejected')?'Una richiesta di stop non è riuscita. Riprova.':'Stop inviato a Comfy. Le richieste già completate dal servizio possono essere addebitate.',results.some(r=>r.status==='rejected'));
 }
 async refreshLibrary(){if(!this.bridge.library||this.closed)return;try{this.library=await this.bridge.library();if(this.closed)return;for(const r of this.library.filter(r=>r.imported)){const existing=this.state.results.find(j=>j.id===r.id);if(existing)Object.assign(existing,r);}this.renderFilters();this.renderGallery();}catch(e){this.note('Libreria temporaneamente non disponibile.',true);}}
 async run(){
  if(this.busy)return;try{validateState(this.state);}catch(e){this.note(e.message,true);return;}
  this.stopRequested=false;this.busy=true;this.updateHeader();const snapshot=copy(this.state),batch=crypto.randomUUID(),started=Date.now();
  const jobs=plannedJobs(snapshot).map((p,ordinal)=>({...p,id:crypto.randomUUID(),batch,started,batchStarted:started,ordinal,status:'submitting',images:[]}));
  try{
   const primary=activeReferences(snapshot).find(r=>r.kind==='image');
   for(const ref of activeReferences(snapshot).filter(r=>r.kind==='image'&&r.process?.enabled)){
    if((ref.process.source==='prompt'&&ref.process.mask)||(ref===primary&&snapshot.mode==='image'&&snapshot.imageEdit)){
     this.note(ref.process.source==='prompt'?'Preparazione maschera SAM3…':'Preparazione Image 1…');const prepared=await this.bridge.previewReference(ref,ref.process);ref.processedPreview=prepared.file;
     if(prepared.maskFile)Object.assign(ref.process,{maskFile:prepared.maskFile,samSource:prepared.samSource,samPrompt:prepared.samPrompt,samSegment:prepared.samSegment});
    }
   }
   const seed=new Uint32Array(1);crypto.getRandomValues(seed);const compiled=compileBatch(snapshot,jobs,seed[0]%2147483647);
   this.note('Controllo reference e nodi…');await this.bridge.check(snapshot,compiled);if(this.closed||this.stopRequested)return;
   this.state.results.push(...jobs);this.save();this.renderFilters();this.renderGallery();this.galleryViewport.scrollTop=0;
   const promptId=await this.bridge.queue(compiled,batch,this.state);for(const job of jobs){job.promptId=promptId;if(job.status==='submitting')job.status='queued';}for(const [name,d] of this.pendingEvents||[])this.event(name,d);this.pendingEvents=[];if(this.stopRequested)await this.stop();this.save();this.updateCards();this.note(`${jobs.length} generazioni indipendenti inviate in un unico batch parallelo.`);
  }catch(e){for(const j of jobs){if(!terminal.has(j.status)){j.stoppedProgress=this.jobProgress(j).percent;j.status='failed';j.error=e.message;j.finished=Date.now();j.errorVisibleUntil=Date.now()+5000;}}this.save();this.updateCards();this.note(e.message,true);}finally{this.busy=false;if(!this.closed)this.updateHeader();}
 }
 event(name,d){
  if(name==='dogma_video_repair'){const job=this.state.results.find(j=>j.id===d?.job_id);if(job&&!terminal.has(job.status)){job.status='repairing';job.repairProgress=d.value;job.repairStage=d.stage;this.save();this.updateCards();}return;}
  if(!d?.prompt_id)return;const jobs=this.state.results.filter(j=>j.promptId===d.prompt_id);if(!jobs.length){this.pendingEvents ||= [];if(this.busy&&this.pendingEvents.length<200)this.pendingEvents.push([name,d]);return;}
  if(name==='progress_state'){for(const [id,n] of Object.entries(d.nodes||{})){const j=jobs.find(x=>x.generator===String(id));if(j&&!terminal.has(j.status)&&j.status!=='repairing'){if(n.state==='running')j.status='running';if(n.max>0&&n.value>0)j.progress=n.value/n.max;}}}
  if(name==='progress'){const j=jobs.find(x=>x.generator===String(d.node));if(j&&d.max>0&&!terminal.has(j.status)&&j.status!=='repairing'){j.progress=d.value/d.max;j.status='running';}}
  if(name==='executing'&&d.node){const j=jobs.find(x=>x.generator===String(d.node));if(j&&!terminal.has(j.status)&&j.status!=='repairing')j.status='running';}
  if(name==='executed'){
   const job=jobs.find(x=>x.output===String(d.node));if(job&&d.output?.images){const record=d.output.dogma_records?.[0];Object.assign(job,record||{images:d.output.images,status:'completed',finished:Date.now()});this.renderFilters();this.renderGallery();}
  }
  if(name==='execution_error'){const failed=jobs.find(j=>j.generator===String(d.node_id)||j.output===String(d.node_id));for(const job of jobs)if(!terminal.has(job.status)){job.stoppedProgress=this.jobProgress(job).percent;job.status=job===failed?'failed':'cancelled';if(job===failed)job.errorVisibleUntil=Date.now()+5000;job.error=job===failed?d.exception_message:'Batch arrestato da Comfy. Nessun retry automatico.';job.finished=Date.now();}this.note(d.exception_message||'Errore nel batch.',true);}
  if(name==='execution_interrupted')for(const job of jobs)if(!terminal.has(job.status)){job.stoppedProgress=this.jobProgress(job).percent;job.status='cancelled';job.finished=Date.now();}
  if(name==='execution_success'){this.recover();this.refreshCredits();this.refreshLibrary();}this.save();this.updateCards();
 }
 async recover(){
  if(this.recovering||!this.bridge.history||this.closed)return;this.recovering=true;
  try{const history=await this.bridge.history();if(this.closed)return;let changed=false;
   for(const record of Object.values(history||{})){
    const meta=record.prompt?.[3]?.extra_pnginfo?.workflow?.extra?.dogma_api_batch;if(meta?.session!==this.state.session)continue;
    for(const saved of meta.jobs){let job=this.state.results.find(x=>x.id===saved.id);if(!job){job=copy(saved);this.state.results.push(job);changed=true;}if(job.imported)continue;job.promptId=record.prompt[1];const ui=record.outputs?.[job.output];if(ui?.images?.length){const result=ui.dogma_records?.[0]||{images:ui.images,status:'completed',finished:Date.now()};if(JSON.stringify(job.images)!==JSON.stringify(result.images))changed=true;Object.assign(job,result);}else if(record.status?.completed&&!terminal.has(job.status)){job.stoppedProgress=this.jobProgress(job).percent;job.status=record.status.status_str==='success'?'missing':'failed';job.errorVisibleUntil=Date.now()+5000;job.finished=Date.now();job.error='Comfy non ha restituito questo output.';}}
   }
   this.save();if(changed){this.renderFilters();this.renderGallery();}else this.updateCards();
  }catch{this.note('La cronologia non è momentaneamente disponibile. I batch già accettati continuano in Comfy.',true);}finally{this.recovering=false;}
 }
}
