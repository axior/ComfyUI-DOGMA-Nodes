import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ROOT=new URL('.',import.meta.url);
const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('dogma_h3_director_v134.css?v=1.0.39',ROOT);document.head.append(css);
const clone=x=>JSON.parse(JSON.stringify(x));
const el=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
const button=(text,fn,cls='')=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;};
const inputURL=name=>api.apiURL('/view?'+new URLSearchParams({filename:name,type:'input'}));
const viewURL=file=>api.apiURL('/view?'+new URLSearchParams(file));
const film=file=>{const v=el('video');v.controls=true;v.loop=true;v.playsInline=true;v.preload='metadata';v.src=viewURL(file);return v;};
let active=null;

export class DirectorStudio {
 constructor(node){
  this.epoch=0;this.requests=new Set();this.node=node;this.page='prepare';this.data={candidates:[],finals:[]};this.pending=false;this.promptId=null;this.lastNotice='';this.abort=new AbortController();
  const on=(name,fn)=>api.addEventListener(name,fn,{signal:this.abort.signal});
  on('dogma.h3.v2',e=>{if(e.detail.session===this.config?.session)this.applyState(e.detail);});
  on('dogma.h3.v2.progress',e=>{if(e.detail.session===this.config?.session){this.data.progress=e.detail;this.status();}});
  on('progress',e=>{if(this.pending&&(!e.detail.prompt_id||e.detail.prompt_id===this.promptId)){
   this.data.progress={step:e.detail.value,total:e.detail.max};this.status();
  }});
  on('kj_preview_override',e=>{
   const d=e.detail;if(String(d.node_id)!==String(this.data.engine))return;
   if(d.step!=null){this.data.progress={step:d.step,total:d.total_steps??d.total};this.status();}
   if(d.image){this.previewData=`data:${d.mime||'image/jpeg'};base64,${d.image}`;this.previewVideo=d.mime==='video/mp4';this.updateLive();}
   const label=this.dialog?.querySelector('.dg-live-label');if(label)label.textContent=`Anteprima durante il calcolo · step ${d.step??'?'} / ${d.total_steps??d.total??'?'}`;
  });
  on('execution_error',e=>{if(e.detail.prompt_id===this.promptId)this.fail(e.detail.exception_message||'Errore di esecuzione.');});
  on('execution_interrupted',e=>{if(e.detail.prompt_id===this.promptId)this.fail('Generazione interrotta. I provini già pronti restano disponibili.');});
  on('execution_success',e=>{if(e.detail.prompt_id===this.promptId){this.pending=false;this.recover();}});
  on('executing',e=>{if(e.detail?.prompt_id===this.promptId&&e.detail?.node===null){this.pending=false;this.recover();}});
 }
 get widget(){return this.node.widgets.find(w=>w.name==='config');}
 load(){
  const merge=(a,b)=>{for(const[k,v]of Object.entries(b||{}))a[k]=v&&typeof v==='object'&&!Array.isArray(v)?merge(a[k]||{},v):v;return a;};
  let stored;try{stored=JSON.parse(this.widget.value);}catch{stored={};}
  this.config=merge(clone(this.catalog.defaults),stored);
  this.config.session ||= crypto.randomUUID();
 }
 family(task){return task==='ref2v'?'ref2v':'fl2v';}
 turbo(task,steps){
  const name=this.family(task)==='ref2v'?'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors':`minimax_h3_fl2v_turbo_${steps}step_v1.0${steps===4?'_768p':''}_comfyui_bf16.safetensors`;
  return this.catalog.loras.find(x=>x.replaceAll('\\','/').split('/').pop()===name)||name;
 }
 presetValues(phase,kind='dogma',task=this.config.task){
  const s={},base=this.catalog.defaults[phase];
  for(const k of ['sampler','scheduler','steps','shift_video','shift_audio','lying','lying_start','lying_end','turbo_strength'])s[k]=base[k];
  s.turbo=phase==='draft'?this.turbo(task,4):base.turbo;
  if(phase==='finish'){
   s.sigmas=kind==='conservative'?'':'0.9035, 0.8000, 0.6316, 0.3158, 0.0000';s.denoise=kind==='conservative'?.18:.35;
   if(this.family(task)==='ref2v')s.steps=4;
   for(const k of ['ultimate_steps','ultimate_denoise','ultimate_strength'])s[k]=base[k];
   s.ultimate_turbo=this.turbo('i2v',8);
  }
  return s;
 }
 preset(phase,kind='dogma',task=this.config.task){Object.assign(this.config[phase],this.presetValues(phase,kind,task));}
 presetKind(phase,task=this.config.task){
  const same=(a,b,k)=>k.includes('turbo')&&!k.includes('strength')?String(a).replaceAll('\\','/').split('/').pop()===String(b).replaceAll('\\','/').split('/').pop():k==='sigmas'?String(a).replace(/\s/g,'')===String(b).replace(/\s/g,''):String(a)===String(b);
  for(const kind of phase==='draft'?['dogma']:['dogma','conservative']){
   if(Object.entries(this.presetValues(phase,kind,task)).every(([k,v])=>same(this.config[phase][k],v,k)))return kind;
  }
  return 'custom';
 }
 refreshPresetMenus(){for(const x of this.dialog?.querySelectorAll('.dg-preset-select')||[])x.value=this.presetKind(x.dataset.phase,x.dataset.task);}
 renderKeepDetails(){
  const open=[...this.dialog.querySelectorAll('details')].map(x=>!!x.open);
  this.render();[...this.dialog.querySelectorAll('details')].forEach((x,i)=>x.open=open[i]||false);
 }
 presetMenu(parent,phase,task=this.config.task){
  const wrap=el('label','','dg-field');wrap.append(el('span','Preset di campionamento'));
  const select=el('select','','dg-preset-select');select.dataset.phase=phase;select.dataset.task=task;
  const options=phase==='draft'?[['dogma','Standard · Turbo 4 step (predefinito)']]:[['dogma','Standard · raffinamento DOGMA (predefinito)'],['conservative','Conservativo · denoise 0,18']];
  for(const [value,label]of [...options,['custom','Personalizzato']]){const o=el('option',label);o.value=value;o.disabled=value==='custom';select.append(o);}
  select.value=this.presetKind(phase,task);
  select.onchange=()=>{if(select.value==='custom')return;this.preset(phase,select.value,task);this.save();this.renderKeepDetails();};
  wrap.append(select,el('small','La scelta applica i parametri qui sotto. Le modifiche manuali sono indicate come Personalizzato. Le LoRA aggiuntive restano invariate.'));parent.append(wrap);
 }
 switchTask(previous){
  const c=this.config,old=this.family(previous),next=this.family(c.task);
  if(old!==next){
   c.sampling_banks ||= {};c.sampling_banks[old]={draft:clone(c.draft),finish:clone(c.finish)};
   const saved=c.sampling_banks[next];
   if(saved){c.draft=clone(saved.draft);for(const k of ['turbo','turbo_strength','sampler','scheduler','steps','shift_video','shift_audio','lying','lying_start','lying_end','sigmas','denoise'])c.finish[k]=saved.finish[k];}
   else{this.preset('draft');this.preset('finish');}
  }
  this.save();this.render();
 }
 save(){
  if(!this.config)return;
  this.widget.value=JSON.stringify(this.config);this.node.setDirtyCanvas?.(true,true);
  clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>{try{app.graph?.change?.();}catch(e){console.warn('DOGMA: aggiornamento workflow',e);}},250);
 }
 async request(path,opts={}){
  const controller=new AbortController(),epoch=this.epoch;this.requests.add(controller);let expired=false;
  const timeout=setTimeout(()=>{expired=true;controller.abort();},20000);
  try{
   const r=await api.fetchApi(path,{...opts,signal:controller.signal});
   if(!r.ok)throw new Error(`Comfy: ${r.status} ${await r.text()}`);
   const result=await r.json();
   if(epoch!==this.epoch){const e=new Error('Pannello chiuso');e.name='AbortError';throw e;}
   return result;
  }catch(e){
   if(expired)throw new Error('Il server non risponde entro 20 secondi. Puoi chiudere il pannello e riprovare.');
   throw e;
  }finally{clearTimeout(timeout);this.requests.delete(controller);}
 }
 header(){
  const h=el('header','','dg-header'),logo=el('img');logo.src=new URL('dogma_logo_white.png',ROOT);logo.alt='DOGMA';
  h.append(logo,el('div','ORIGINALS / H3 DIRECTOR','dg-brand'),button('Torna a Comfy',()=>this.close()));return h;
 }
 async open(){
  if(active&&active!==this)active.close();
  if(this.dialog?.open)return;
  active=this;const epoch=++this.epoch;this.loading=true;
  const dialog=this.dialog=el('dialog','','dg-studio');dialog.setAttribute('aria-label','DOGMA H3 Director');
  dialog.addEventListener('cancel',e=>{e.preventDefault();this.close();});
  // Keep Comfy shortcuts away from text fields; never synthesize keyboard events.
  for(const name of ['keydown','keyup'])dialog.addEventListener(name,e=>e.stopPropagation());
  dialog.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();this.close();}});
  dialog.append(this.header(),el('nav'),el('div','Caricamento impostazioni…','dg-status'),el('main'),el('footer'));
  document.body.append(dialog);dialog.showModal();
  try{
   this.catalog=await this.request('/dogma/h3/v2/catalog');if(epoch!==this.epoch)return;
   this.load();this.loading=false;this.render();
   await this.recover();if(epoch===this.epoch&&this.dialog)this.poll=setInterval(()=>this.recover(false),3500);
  }catch(e){
   if(epoch!==this.epoch||e.name==='AbortError')return;
   dialog.querySelector('.dg-status').textContent=e.message;
   dialog.querySelector('main').append(button('Riprova',()=>{this.close();this.open();}));
  }
 }
 close(){
  ++this.epoch;clearInterval(this.poll);this.recovering=false;
  for(const c of this.requests)c.abort();this.requests.clear();
  const dialog=this.dialog;this.dialog=null;this.folderPanel=null;if(active===this)active=null;
  try{dialog?.querySelectorAll('video').forEach(v=>v.pause());dialog?.close();}finally{dialog?.remove();}
  this.save();
 }
 destroy(){this.close();clearTimeout(this.saveTimer);this.abort.abort();}
 async browseFolders(){
  if(this.folderPanel||!this.dialog)return;
  const epoch=this.epoch,panel=el('section','','dg-folder-browser');this.folderPanel=panel;
  panel.setAttribute('role','region');panel.setAttribute('aria-label','Scegli cartella output');
  const main=this.dialog.querySelector('main');main.prepend(panel);
  const input=el('input');input.type='text';input.value=this.config.output_dir||'';input.setAttribute('aria-label','Percorso cartella');
  const info=el('p'),list=el('div','','dg-folders');let busy=false,current='';
  const done=()=>{panel.remove();if(this.folderPanel===panel)this.folderPanel=null;};
  const use=button('Usa questa cartella',()=>{this.config.output_dir=current;this.save();done();this.render();},'dg-primary');use.disabled=true;
  const go=button('Vai',()=>load(input.value));
  panel.append(el('h2','Cartella di salvataggio'),el('p','Naviga nelle cartelle del computer che esegue Comfy.'),input,go,button('Annulla',done),use,info,list);
  const load=async path=>{
   if(busy)return;busy=true;go.disabled=true;use.disabled=true;info.textContent='Caricamento cartelle…';list.replaceChildren();
   try{
    const r=await this.request('/dogma/h3/v2/folders?'+new URLSearchParams({path:path||''}));
    if(epoch!==this.epoch||this.folderPanel!==panel)return;
    current=r.path;input.value=current;info.textContent=r.truncated?'Mostrate le prime 500 cartelle. Puoi inserire il percorso completo.':'Seleziona una sottocartella oppure conferma questa cartella.';
    if(r.parent)list.append(button('↑ Cartella superiore',()=>load(r.parent)));
    for(const d of r.drives||[])list.append(button(d.name,()=>load(d.path)));
    for(const d of r.directories||[])list.append(button('📁 '+d.name,()=>load(d.path)));
    use.disabled=false;
   }catch(e){if(epoch===this.epoch&&this.folderPanel===panel&&e.name!=='AbortError')info.textContent=e.message;}
   finally{busy=false;go.disabled=false;}
  };
  input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();load(input.value);}});
  await load(input.value);
 }
 sound(){
  if(!this.config.sound)return;
  try{this.audio ||= new (window.AudioContext||window.webkitAudioContext)();this.audio.resume();const t=this.audio.currentTime;
   for(let i=0;i<2;i++){const o=this.audio.createOscillator(),g=this.audio.createGain();o.connect(g);g.connect(this.audio.destination);o.frequency.value=660+i*220;g.gain.setValueAtTime(0,t+i*.18);g.gain.linearRampToValueAtTime(.07,t+i*.18+.015);g.gain.exponentialRampToValueAtTime(.001,t+i*.18+.14);o.start(t+i*.18);o.stop(t+i*.18+.15);}
  }catch{}
 }
 armSound(){if(this.config.sound){try{this.audio ||= new(window.AudioContext||window.webkitAudioContext)();this.audio.resume();}catch{}}}
 applyState(d){
  const change=this.data.status!==d.status||this.data.candidates?.length!==d.candidates?.length||this.data.finals?.length!==d.finals?.length;
  this.data=d;
  if(['ready','developed','done','error'].includes(d.status)){this.pending=false;d.progress=null;const key=d.run+':'+d.status+':'+d.message;if(key!==this.lastNotice){this.lastNotice=key;this.sound();}}
  if(change&&this.page!=='prepare')this.render();else this.status();
 }
 async recover(render=true){
  if(!this.config||!this.dialog||this.loading||this.recovering)return;const epoch=this.epoch;this.recovering=true;
  try{
   const d=await this.request('/dogma/h3/v2/session/'+this.config.session);
   const q=await this.request('/queue');
   const jobs=[...(q.queue_running||[]),...(q.queue_pending||[])];
   const owned=jobs.find(x=>this.promptId?x[1]===this.promptId:JSON.stringify(x[2]||{}).includes(this.config.session));
   if(owned){this.promptId=owned[1];this.pending=true;if(!['running','error'].includes(d.status)){d.status='running';d.message='In coda · attendo il motore';}}
   else if(d.status==='running'){
    d.status='idle';d.message=jobs.length?'DOGMA non è in esecuzione. Comfy sta elaborando un altro lavoro.':'Il lavoro DOGMA non è più in coda. I provini salvati restano disponibili; controlla eventuali errori in Comfy.';this.pending=false;
   }else if(!owned)this.pending=false;
   if(owned&&d.status==='running'&&d.run===this.data.run&&d.message===this.data.message&&!d.progress)d.progress=this.data.progress;
   if(render||JSON.stringify(d)!==JSON.stringify(this.data))this.applyState(d);else this.status();
  }catch(e){if(epoch===this.epoch&&e.name!=='AbortError'){this.data.message='Stato non disponibile: '+e.message;this.status();}}
  finally{if(epoch===this.epoch)this.recovering=false;}
 }
 fail(message){this.pending=false;this.data.status='error';this.data.progress=null;this.data.message=message;this.status();this.sound();}
 status(){
  const s=this.dialog?.querySelector('.dg-status');if(s){s.textContent=this.data.message||'Prepara il lavoro, genera i provini e scegli quale continuare.';s.dataset.state=this.data.status;}
  this.dialog?.querySelectorAll('[data-queue]').forEach(b=>b.disabled=this.pending||this.submitting);
  const bar=this.dialog?.querySelector('.dg-progress');if(bar){const p=this.data.progress;bar.hidden=!this.pending;bar.max=p?.total||1;bar.value=p?.step||0;}
  const detail=this.dialog?.querySelector('.dg-progress-label');if(detail)detail.textContent=this.pending?(this.data.progress?`Passaggio corrente: ${this.data.progress.step} / ${this.data.progress.total}`:'Elaborazione in corso · attendo avanzamento o anteprima') : '';
  // Always allow a fresh queue check: UI state can lag behind a failed job.
  const stop=this.dialog?.querySelector('[data-stop]');if(stop){stop.disabled=!!this.stopping;stop.textContent=this.pending?'Interrompi':'Verifica / interrompi';}
 }
 async queue(action){
  if(this.pending||this.submitting)return;this.submitting=true;this.armSound();
  try{
   if(action!=='draft'&&!this.config.selected)throw new Error('Scegli prima un provino.');
   if(action==='draft'){
    if(this.config.task==='i2v'&&!this.config.first&&!this.config.last)throw new Error('Carica il primo o l’ultimo fotogramma.');
    if(this.config.task==='ref2v'&&!this.config.refs.length)throw new Error('Carica almeno una reference.');
    if(this.config.exploration==='prompts'&&this.config.variants.some(v=>!v.text.trim()))throw new Error('Completa o rimuovi le schede prompt vuote.');
    if(this.config.exploration==='seeds'&&!this.config.prompt.trim())throw new Error('Scrivi un prompt.');
    const checkpoint=this.config.models[this.config.task];
    if(!this.catalog.models.includes(checkpoint))throw new Error('Seleziona un checkpoint installato per '+this.config.task.toUpperCase()+' nelle impostazioni avanzate.');
    if(this.config.refs.some(r=>!r.name)&&this.config.task==='ref2v')throw new Error('Carica o rimuovi le reference vuote.');
   }
   if(action==='finish'&&!this.data.developments?.some(p=>p.id===this.config.selected_development&&p.candidate===this.config.selected))throw new Error('Scegli prima uno sviluppo di qualità.');
   const required=[];
   if(action==='develop'&&this.config.develop.mode==='guided')required.push('MinimaxH3LatentUpscaler3D');
   if(this.config.preview.enabled)required.push('ModelPreviewOverrideKJ');
   if(action==='finish'&&this.config.finish.stages!=='ultimate')required.push('MinimaxH3LatentUpscaler3D');
   if(action==='finish'&&this.config.finish.stages!=='latent')required.push('UltimateSDUpscaleNoUpscaleGuider');
   const missing=required.filter(n=>!this.catalog.nodes.includes(n));if(missing.length)throw new Error('Installa dal Manager i nodi richiesti: '+missing.join(', '));
   const q=await this.request('/queue');if(q.queue_running?.length||q.queue_pending?.length)throw new Error('Comfy sta già lavorando. Attendi la fine della coda.');
   this.config.action=action;this.config.nonce++;this.save();
   this.previewData=null;this.previewVideo=false;
   this.pending=true;this.data.status='running';this.data.progress=null;this.data.message='Invio a Comfy…';this.status();
   const graph=await app.graphToPrompt();
   // Direct API returns a prompt_id; app.queuePrompt() may return false for accepted queued work.
   const result=await api.queuePrompt(0,graph);
   if(!result?.prompt_id)throw new Error('Comfy non ha restituito un identificativo di esecuzione.');
   this.promptId=result.prompt_id;this.page=action==='draft'?'choose':action==='develop'?'develop':'finish';this.data.message='In coda · attendo il motore';this.render();
  }catch(e){if(e.name!=='AbortError'){const detail=e.response?.node_errors||e.response?.error;this.fail(detail?JSON.stringify(detail,null,2):e.message);}}finally{this.submitting=false;this.status();}
 }
 async stop(){
  if(this.stopping)return;this.stopping=true;this.status();
  try{
  const q=await this.request('/queue');
  const own=x=>this.promptId?x[1]===this.promptId:JSON.stringify(x[2]||{}).includes(this.config.session);
  if(q.queue_running?.some(own))await api.interrupt();
  else if(q.queue_pending?.some(own))await this.request('/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete:q.queue_pending.filter(own).map(x=>x[1])})});
  else {this.data.message=this.data.status==='error'?this.data.message+' · Coda verificata: questo lavoro è terminato.':'Nessun lavoro DOGMA da interrompere. Le altre generazioni non vengono fermate.';this.pending=false;this.data.progress=null;return;}
  this.data.message='Interruzione richiesta · attendo Comfy';this.status();
  }finally{this.stopping=false;this.status();}
 }
 field(parent,label,obj,key,opts={}){
  const wrap=el('label','','dg-field');wrap.append(el('span',label));let x;
  if(opts.options){x=el('select');for(const value of opts.options){const [v,t,disabled]=Array.isArray(value)?value:[value,value];const o=el('option',t);o.value=v;o.disabled=!!disabled;x.append(o);}if(![...x.options].some(o=>o.value===String(obj[key]))&&obj[key]){const o=el('option',obj[key]+' · non disponibile');o.value=obj[key];x.append(o);}x.value=obj[key]??'';}
  else if(opts.multi){x=el('textarea');x.rows=opts.rows||5;x.value=obj[key]??'';}
  else{x=el('input');x.type=opts.type||'text';if(x.type==='checkbox')x.checked=!!obj[key];else x.value=obj[key]??'';if(opts.min!=null)x.min=opts.min;if(opts.max!=null)x.max=opts.max;if(opts.step!=null)x.step=opts.step;}
  x.oninput=()=>{obj[key]=x.type==='checkbox'?x.checked:x.type==='number'?Number(x.value):x.value;this.save();this.refreshPresetMenus();};
  x.onchange=()=>{x.oninput();opts.change?.();};wrap.append(x);if(opts.hint)wrap.append(el('small',opts.hint));parent.append(wrap);return x;
 }
 section(parent,title){const p=el('section','','dg-card');p.append(el('h2',title));parent.append(p);return p;}
 loras(parent,stack,title){
  const d=el('details','','dg-loras');d.append(el('summary',`${title} · ${stack.length}`));parent.append(d);
  const draw=()=>{
   [...d.children].slice(1).forEach(e=>e.remove());d.firstChild.textContent=`${title} · ${stack.length}`;
   stack.forEach((l,i)=>{const row=el('div','','dg-lora-row');this.field(row,'LoRA',l,'name',{options:['',...this.catalog.loras]});this.field(row,'Potenza',l,'strength',{type:'number',step:.01,min:-10,max:10});row.append(button('Rimuovi',()=>{stack.splice(i,1);this.save();draw();}));d.append(row);});
   d.append(button('+ Aggiungi LoRA',()=>{stack.push({name:'',strength:1});this.save();draw();}));
  };draw();
 }
 asset(parent,title,obj,key,kind='image',remove){
  const p=this.section(parent,title);const name=obj[key];
  if(name){const media=el(kind==='video'?'video':'img');media.src=inputURL(name);if(kind==='video')media.controls=true;media.className='dg-asset';p.append(media,el('small',name));}
  const upload=el('input');upload.type='file';upload.accept=kind==='video'?'video/*':'image/*';upload.hidden=true;
  upload.onchange=async()=>{const file=upload.files?.[0];if(!file)return;try{const data=new FormData();data.append('image',file);data.append('type','input');data.append('subfolder','DOGMA_DIRECTOR');const res=await this.request('/upload/image',{method:'POST',body:data});obj[key]=(res.subfolder?res.subfolder+'/':'')+res.name;this.save();this.render();}catch(e){if(e.name!=='AbortError')this.fail(e.message);}};
  p.append(upload,button(name?'Cambia file':'Carica file',()=>upload.click()));
  if(name||remove)p.append(button('Rimuovi',()=>{if(remove)remove();else obj[key]='';this.save();this.render();}));
  return p;
 }
 render(){
  if(!this.dialog||this.loading)return;
  this.folderPanel=null;this.dialog.querySelectorAll('video').forEach(v=>v.pause());this.dialog.replaceChildren();
  this.dialog.append(this.header());
  const nav=el('nav');for(const [key,label]of[['prepare','01 Prepara'],['choose','02 Scegli'],['develop','03 Sviluppa'],['finish','04 Finalizza']])nav.append(button(label,()=>{this.page=key;this.render();},this.page===key?'is-active':''));
  const fresh=button('Nuova sessione',()=>{if(this.pending)return;if(!window.confirm('Avviare una nuova sessione? I video precedenti restano salvati. Salva il workflow in Comfy per poter riaprire anche la galleria precedente.'))return;this.config.session=crypto.randomUUID();this.config.selected='';this.config.action='draft';this.config.selected_development='';this.data={candidates:[],developments:[],finals:[],status:'new'};this.promptId=null;this.A=this.B=null;this.previewData=null;this.page='prepare';this.save();this.render();});fresh.dataset.queue='';nav.append(fresh);
  const stop=button('Interrompi',()=>this.stop().catch(e=>{this.data.message='Interruzione non confermata: '+e.message;this.status();}));stop.dataset.stop='';nav.append(stop);const state=el('div','','dg-state');state.append(el('div','','dg-status'),el('progress','','dg-progress'),el('small','','dg-progress-label'));this.dialog.append(nav,state);
  const body=el('main');this.dialog.append(body);
  if(this.page==='prepare')this.prepare(body);if(this.page==='choose')this.choose(body);if(this.page==='develop')this.develop(body);if(this.page==='finish')this.finish(body);
  const foot=el('footer','Salvataggio automatico della sessione · Cartella output configurabile in Prepara · Esc torna a Comfy');this.dialog.append(foot);this.status();
 }
 prepare(body){
  const c=this.config;const intro=this.section(body,'Il tuo lavoro');const row=el('div','','dg-grid');intro.append(row);
  const previousTask=c.task;
  this.field(row,'Nome lavoro',c,'job');this.field(row,'Cosa vuoi creare?',c,'task',{options:[['i2v','Da immagini · primo e/o ultimo frame'],['t2v','Da testo · nessuna immagine'],['ref2v','Da reference · immagini e video']],change:()=>this.switchTask(previousTask)});
  this.field(intro,'Cartella output · vuoto = cartella Comfy',c,'output_dir',{hint:'Percorso assoluto sul computer dove gira Comfy. I video vengono copiati qui e restano visibili nella galleria.'});
  intro.append(button('Scegli cartella…',()=>this.browseFolders()));
  this.field(intro,'Genera audio nei video',c,'generate_audio',{type:'checkbox',hint:'Disattivato: provini e finali vengono esportati senza traccia audio. H3 mantiene internamente i latenti audiovisivi.'});
  const assets=el('div','','dg-grid');body.append(assets);
  if(c.task==='i2v'){this.asset(assets,'Primo fotogramma · facoltativo',c,'first');this.asset(assets,'Ultimo fotogramma · facoltativo',c,'last');}
  if(c.task==='ref2v'){
   let image=0,video=0;c.refs.forEach((r,i)=>this.asset(assets,r.kind==='image'?`Picture ${++image}`:`Video ${++video}`,r,'name',r.kind,()=>c.refs.splice(i,1)));
   const p=this.section(assets,'Reference');p.append(el('p','Nel prompt usa <Picture 1>, <Picture 2>, <Video 1>… Dei video viene usato l’inizio, per la durata richiesta (massimo 15 secondi), ricampionato a 24 fps. Il loro audio non viene usato come reference.'));
   if(image<9)p.append(button('+ Immagine',()=>{c.refs.push({kind:'image',name:''});this.save();this.render();}));
   if(video<3)p.append(button('+ Video',()=>{c.refs.push({kind:'video',name:''});this.save();this.render();}));
  }
  const prompt=this.section(body,'Esplora una direzione');this.field(prompt,'Prompt comune',c,'prompt',{multi:true,rows:7,hint:'Può contenere tutti i paragrafi necessari. In modalità Prompt diversi puoi lasciarlo vuoto e scrivere prompt completi nelle schede.'});
  this.field(prompt,'Tipo di confronto',c,'exploration',{options:[['seeds','Seed diversi · stesso prompt'],['prompts','Prompt diversi · stesso seed']],change:()=>this.render()});
  this.field(prompt,c.exploration==='seeds'?'Seed iniziale · i provini successivi usano +1':'Seed condiviso',c,'seed',{type:'number',min:0,max:9007199254740990,step:1});
  prompt.append(button('Nuovi seed',()=>{c.seed=Math.floor(Math.random()*1e12);this.save();this.render();}));
  this.loras(prompt,c.common_loras,'LoRA comuni a tutti i provini');
  if(c.exploration==='seeds'){
   this.field(prompt,'Quanti provini?',c,'count',{type:'number',min:1,max:10,step:1,change:()=>this.render()});
   for(let i=0;i<c.count;i++){c.trial_loras[String(i)] ||= [];this.loras(prompt,c.trial_loras[String(i)],`LoRA aggiuntive · provino ${i+1}`);}
  }else{
   c.variants.forEach((v,i)=>{const card=this.section(prompt,`Prompt ${i+1}`);this.field(card,'Testo completo',v,'text',{multi:true,rows:7});this.loras(card,v.loras ||= [],'LoRA aggiuntive');if(c.variants.length>1)card.append(button('Elimina questa variante',()=>{c.variants.splice(i,1);this.save();this.render();}));});
   if(c.variants.length<10)prompt.append(button('+ Nuovo prompt',()=>{c.variants.push({text:'',loras:[]});this.save();this.render();}));
  }
  const size=this.section(body,'Formato dei provini');const sizes=el('div','','dg-grid');size.append(sizes);
  this.field(sizes,'Proporzioni automatiche dalla prima immagine disponibile',c,'auto_aspect',{type:'checkbox',change:()=>this.render()});
  if(c.auto_aspect&&c.task!=='t2v')this.field(sizes,'Lato lungo del provino',c,'long_edge',{type:'number',min:256,max:1536,step:32});
  else {this.field(sizes,'Larghezza',c,'width',{type:'number',min:128,max:2048,step:32});this.field(sizes,'Altezza',c,'height',{type:'number',min:128,max:2048,step:32});}
  this.field(sizes,'Durata richiesta · secondi',c,'seconds',{type:'number',min:.2,max:15,step:.1});
  size.append(el('p','Dimensioni allineate a 32 px, durata alla griglia H3 (17k+5 frame a 24 fps). Il risultato indica le misure effettive. I provini piccoli possono cambiare movimento rispetto al finale; il tempo dipende da GPU, modello e LoRA.'));
  this.field(size,'Suono quando serve la tua attenzione',c,'sound',{type:'checkbox'});
  this.advanced(body);
  const go=button('Genera provini',()=>this.queue('draft'),'dg-primary');go.dataset.queue='';body.append(go);
 }
 advanced(body){
  const c=this.config;const d=el('details','','dg-card');d.append(el('summary','Impostazioni avanzate · modelli, campionamento e anteprima'));body.append(d);
  const models=this.section(d,'Modelli installati');this.field(models,`Checkpoint ${c.task.toUpperCase()}`,c.models,c.task,{options:['',...this.catalog.models]});
  for(const [k,label,list]of[['clip','Text encoder',this.catalog.clip],['vae','Video VAE',this.catalog.vae],['audio','Audio VAE',this.catalog.vae]])this.field(models,label,c.models,k,{options:list});
  models.append(el('p','I2V e T2V condividono le impostazioni FL2V. Ref2V conserva un preset separato con Turbo compatibile. Tornando a una modalità ritrovi le sue impostazioni.'));
  const p=this.section(d,'Campionamento dei provini');this.presetMenu(p,'draft');this.sampleFields(p,c.draft);
  const live=this.section(d,'Anteprima durante la generazione');this.field(live,'Anteprima KJ attiva',c.preview,'enabled',{type:'checkbox'});this.field(live,'Tiny VAE',c.preview,'tiny_vae',{options:this.catalog.tiny_vae});this.field(live,'Risoluzione massima',c.preview,'max_resolution',{type:'number',step:32,min:128,max:1024});
  live.append(el('p','Si aggiorna quando il sampler fornisce un passo. Non è un secondo video generato e non garantisce un aggiornamento ogni secondo.'));
 }
 sampleFields(p,s){
  const g=el('div','','dg-grid');p.append(g);
  this.field(g,'LoRA Turbo · vuoto = disattiva',s,'turbo',{options:['',...this.catalog.loras]});this.field(g,'Potenza Turbo',s,'turbo_strength',{type:'number',step:.01});
  this.field(g,'Sampler',s,'sampler',{options:this.catalog.samplers});this.field(g,'Scheduler',s,'scheduler',{options:this.catalog.schedulers});this.field(g,'Step',s,'steps',{type:'number',min:1,max:100,step:1});
  this.field(g,'Shift video',s,'shift_video',{type:'number',step:.1});this.field(g,'Shift audio',s,'shift_audio',{type:'number',step:.1});
  this.field(g,'Lying Sigma · 0 = disattivo',s,'lying',{type:'number',step:.001,min:-.99,max:1});this.field(g,'Lying · inizio 0–1',s,'lying_start',{type:'number',step:.01,min:0,max:1});this.field(g,'Lying · fine 0–1',s,'lying_end',{type:'number',step:.01,min:0,max:1});
 }
 live(body){
  const p=this.section(body,'Anteprima live');p.classList.add('dg-live');p.append(el('p',this.pending?'In attesa del prossimo step…':'Ultima anteprima disponibile','dg-live-label'));
  const slot=el('div','','dg-live-slot');p.append(slot);this.updateLive();
 }
 updateLive(){
  const slot=this.dialog?.querySelector('.dg-live-slot');if(!slot||!this.previewData)return;
  const tag=this.previewVideo?'video':'img';let media=slot.firstChild;
  if(!media||media.tagName.toLowerCase()!==tag){media=el(tag,'','dg-live-image');if(this.previewVideo){media.autoplay=true;media.loop=true;media.muted=true;media.playsInline=true;}slot.replaceChildren(media);}
  media.src=this.previewData;media.hidden=false;
 }
 choose(body){
  this.live(body);const items=this.data.candidates||[];
  if(!items.length){body.append(el('p','I provini appariranno qui appena decodificati. Puoi tornare a Comfy senza interrompere il lavoro.'));return;}
  const grid=el('div','','dg-gallery');body.append(grid);
  items.forEach(p=>{
   const card=this.section(grid,p.label);if(p.id===this.config.selected)card.classList.add('is-selected');card.append(film(p.video),el('p',`${p.width} × ${p.height} · ${(p.frames/24).toFixed(2)} s · seed ${p.seed}`));
   const txt=el('details');txt.append(el('summary','Prompt e LoRA del provino'),el('pre',p.prompt),el('pre',p.loras.map(l=>`${l.name} · ${l.strength}`).join('\n')||'Nessuna LoRA aggiuntiva'));card.append(txt);
   card.append(button('Scegli e sviluppa',()=>{this.config.selected=p.id;this.config.selected_development='';this.save();this.page='develop';this.render();},'dg-primary'));
   for(const side of ['A','B'])card.append(button('Confronta '+side,()=>{this[side]=p.id;this.render();}));
  });
  const a=items.find(p=>p.id===this.A),b=items.find(p=>p.id===this.B);
  if(a&&b){const compare=this.section(body,'Confronto A / B');const g=el('div','','dg-grid');const av=film(a.video),bv=film(b.video);av.muted=bv.muted=true;g.append(av,bv);compare.append(g,button('Riproduci insieme',()=>{av.currentTime=bv.currentTime=0;av.play();bv.play();}),button('Pausa',()=>{av.pause();bv.pause();}));}
 }
 develop(body){
  const p=this.data.candidates?.find(x=>x.id===this.config.selected);
  if(!p){body.append(el('p','Scegli prima una bozza.'));return;}
  const src=this.section(body,p.label+' · bozza scelta');src.append(film(p.video));
  const s=this.section(body,'Sviluppo di qualità');const d=this.config.develop;
  this.field(s,'Metodo',d,'mode',{options:[['guided','Continua la bozza scelta (predefinito)'],['native','Rigenera in qualità · il movimento può cambiare']]});
  this.field(s,'Lato lungo dello sviluppo',d,'long_edge',{type:'number',min:512,max:1536,step:32});
  s.append(el('p','Standard: circa 960 × 544 per 16:9, 20 step senza Turbo. Continua usa i latenti salvati della bozza; prompt, seed, sorgenti e LoRA vengono ripresi automaticamente. La risoluzione maggiore può cambiare dettagli e movimento.'));
  const adv=el('details','','dg-card');adv.append(el('summary','Campionamento dello sviluppo'));body.append(adv);
  this.field(adv,'Denoise · solo Continua (maggiore = più cambiamento)',d,'denoise',{type:'number',min:.01,max:.99,step:.01});this.sampleFields(adv,d);
  const go=button('Sviluppa questo',()=>this.queue('develop'),'dg-primary');go.dataset.queue='';body.append(go);this.live(body);
  const grid=el('div','','dg-gallery');body.append(grid);
  for(const item of (this.data.developments||[]).filter(x=>x.candidate===p.id)){
   const card=this.section(grid,item.label);card.append(film(item.video),el('p',`${item.width} × ${item.height} · ${item.mode==='guided'?'Continuazione':'Rigenerazione'} · seed ${item.seed}`),el('p',item.saved_path||''));
   card.append(button('Usa questo sviluppo → Finalizza',()=>{this.config.selected_development=item.id;this.save();this.page='finish';this.render();},'dg-primary'));
  }
 }
 finish(body){
  const p=this.data.developments?.find(x=>x.id===this.config.selected_development&&x.candidate===this.config.selected);
  if(!p){body.append(el('p','Scegli uno sviluppo di qualità nella sezione Sviluppa.'));return;}
  const selected=this.section(body,p.label+' · selezionato');selected.append(film(p.video),el('p','Prompt, seed, sorgenti, modello e LoRA sono ripresi automaticamente da questo provino.'));
  const f=this.config.finish;const s=this.section(body,'Come vuoi finalizzare?');
  const task=p.config?.task||this.config.task;
  this.field(s,'Passaggi',f,'stages',{options:[['both','Completo · latent upscale + Ultimate'],['latent','Solo latent upscale e raffinamento'],['ultimate','Solo Ultimate dallo sviluppo']],change:()=>this.render()});
  this.field(s,'Risoluzione finale · lato lungo',f,'resolution',{options:[['1k','1K · 1024 px'],['2k','2K · 2048 px'],['3k','3K · 3072 px'],['4k','4K · 4096 px']],change:()=>this.render()});
  const edge={ '1k':1024,'2k':2048,'3k':3072,'4k':4096 }[f.resolution];
  s.append(el('p',`Uscita: ${Math.max(32,Math.round(p.width/Math.max(p.width,p.height)*edge/32)*32)} × ${Math.max(32,Math.round(p.height/Math.max(p.width,p.height)*edge/32)*32)} px. Proporzioni del provino, allineate a 32 px. Completo usa un passaggio latente fino a ×2 e Ultimate alla risoluzione scelta.`));
  s.append(el('small','Il raffinamento può modificare i dettagli. 3K/4K richiedono più memoria e tempo; il solo passaggio latente può superare la memoria disponibile.'));
  const rate={value:this.config.rife.enabled?String(this.config.rife.fps):'original'};
  this.field(s,'Fotogrammi al secondo finali',rate,'value',{options:[['original','Originali · 24 fps — senza RIFE'],['48','48 fps · RIFE'],['60','60 fps · RIFE']],change:()=>{
   this.config.rife.enabled=rate.value!=='original';if(this.config.rife.enabled)this.config.rife.fps=Number(rate.value);this.save();this.renderKeepDetails();
  }});
  if(this.config.rife.enabled){
   s.append(el('p','Ordine: latent e raffinamento → RIFE → Ultimate. Con Solo latent si ferma dopo RIFE; con Solo Ultimate interpola prima dei tasselli. La durata e l’audio restano invariati. Il video interpolato viene salvato anche separatamente. Richiede ComfyUI-VFI e il modello RIFE installato.'));
   if(!this.catalog.nodes.includes('RIFEInterpolation'))s.append(el('p','RIFE non disponibile: installa ComfyUI-VFI dal Manager oppure scegli Originali nella tendina dei fotogrammi al secondo.'));
  }
  const d=el('details','','dg-card');d.append(el('summary','Controlli finalizzazione'));body.append(d);this.presetMenu(d,'finish',task);this.sampleFields(d,f);
  this.field(d,'Modello latent upscale',f,'upscaler',{options:this.catalog.upscalers});this.field(d,'Sigma del raffinamento · vuoto usa scheduler',f,'sigmas');this.field(d,'Denoise raffinamento · solo senza sigma manuali',f,'denoise',{type:'number',step:.01,min:0,max:1});
  this.field(d,'Sampler Ultimate',f,'ultimate_sampler',{options:this.catalog.samplers});
  this.field(d,'Seed raffinamento',f,'refine_seed',{type:'number',step:1});
  this.field(d,'Seed Ultimate',f,'ultimate_seed',{type:'number',step:1});
  this.field(d,'Checkpoint per Ultimate',f,'ultimate_model',{options:this.catalog.models});this.field(d,'Turbo FL2V per Ultimate',f,'ultimate_turbo',{options:['',...this.catalog.loras]});this.field(d,'Potenza Turbo Ultimate',f,'ultimate_strength',{type:'number',step:.01});
  for(const [k,label,step]of[['tile_width','Larghezza tasselli',32],['tile_height','Altezza tasselli',32],['tile_padding','Contesto tasselli',8],['mask_blur','Sfumatura tasselli',1],['ultimate_steps','Step Ultimate',1],['ultimate_denoise','Denoise Ultimate',.01]])this.field(d,label,f,k,{type:'number',step});
  this.field(d,'RIFE · batch (1 riduce la memoria)',this.config.rife,'batch_size',{type:'number',min:1,max:32,step:1});
  const go=button('Finalizza questo',()=>this.queue('finish'),'dg-primary');go.dataset.queue='';body.append(go,button('Torna ai provini',()=>{this.page='choose';this.render();}));this.live(body);
  const out=el('div','','dg-gallery');body.append(out);
  for(const item of (this.data.finals||[]).filter(x=>!x.candidate||x.candidate===p.id)){
   const card=this.section(out,item.label);card.append(film(item.video),el('p',item.saved_path||'Risultato precedente · cartella Comfy','dg-saved-path'));
   if(item.fps)card.append(el('p',`${item.width} × ${item.height} · ${item.fps} fps · ${item.frames} fotogrammi · ${(item.frames/item.fps).toFixed(2)} s`));
   if(item.saved_path){const open=button('Apri cartella',async()=>{if(open.disabled)return;open.disabled=true;try{await this.request('/dogma/h3/v2/open-folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:this.config.session,id:item.id})});}catch(e){if(e.name!=='AbortError')this.fail(e.message);}finally{open.disabled=false;}});card.append(open);}
  }
 }
}

app.registerExtension({name:'DOGMA.H3.Director.V2',async beforeRegisterNodeDef(Node,data){
 if(data.name!=='DOGMAH3DirectorConsoleV2')return;
 const created=Node.prototype.onNodeCreated;
 Node.prototype.onNodeCreated=function(){
  created?.apply(this,arguments);this._dogmaV2=new DirectorStudio(this);
  const w=this.widgets.find(x=>x.name==='config');if(w){w.type='converted-widget';w.computeSize=()=>[0,-4];w.hidden=true;}
  this.addWidget('button','APRI DOGMA STUDIO',null,()=>this._dogmaV2.open().catch(e=>app.extensionManager?.toast?.add({severity:'error',summary:'DOGMA',detail:e.message,life:9000})));
  this.setSize([380,120]);
 };
 const removed=Node.prototype.onRemoved;Node.prototype.onRemoved=function(){this._dogmaV2?.destroy();return removed?.apply(this,arguments);};
}});
