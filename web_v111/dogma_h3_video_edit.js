import { MaskEditor, compositeControls } from './dogma_h3_edit_mask.js?v=studio-1-0-47';
import { EditComparison } from './dogma_h3_edit_compare.js?v=studio-1-0-47';
import { api } from '../../scripts/api.js';
import { inputFile, viewURL, mediaPreview } from './dogma_h3_media.js?v=studio-1-0-47';
import { frameIndex, frameTime, frameCount, snapSelection, stepTime, parseSelection } from './dogma_h3_timing.js?v=studio-1-0-47';
export { snapSelection } from './dogma_h3_timing.js?v=studio-1-0-47';

const el=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
const button=(text,fn)=>{const e=el('button',text);e.type='button';e.onclick=fn;return e;};
const url=(path,params)=>api.apiURL(path+'?'+new URLSearchParams(params));
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
export const clock=t=>{const m=Math.floor(t/60),s=t-m*60;return `${String(m).padStart(2,'0')}:${s.toFixed(3).padStart(6,'0')}`;};

export function renderEditor(studio,body){
 const c=studio.config,e=c.edit;
 const section=studio.section(body,'Video originale · scegli il tratto da modificare');
 const upload=el('input');upload.type='file';upload.accept='video/*';upload.hidden=true;
 const load=button(e.source?'Cambia video':'Carica video',()=>upload.click());
 const uploadStatus=el('small');
 upload.onchange=async()=>{
  const file=upload.files?.[0];if(!file)return;
  studio.uploads=(studio.uploads||0)+1;studio.status();load.disabled=true;uploadStatus.textContent='Caricamento del video sul server…';
  try{
   const data=new FormData();data.append('image',file);data.append('type','input');data.append('subfolder','DOGMA_DIRECTOR');
   const r=await studio.request('/upload/image',{method:'POST',body:data});
   e.source=(r.subfolder?r.subfolder+'/':'')+r.name;e.start=0;e.end=107/24;
   studio.editMeta=null;studio.save();studio.render();
  }catch(err){if(err.name!=='AbortError')studio.fail(err.message);}
  finally{studio.uploads--;studio.status();load.disabled=false;uploadStatus.textContent='';}
 };
 section.append(upload,load,uploadStatus);
 if(e.source){
  section.append(el('small',e.source));
  const timeline=el('div','','dg-edit-panel');section.append(timeline);
  studio.editTimeline=new EditTimeline(studio,timeline,e);
 }
 studio.maskEditor=new MaskEditor(studio,body);
 const refs=studio.section(body,'Reference per la modifica');
 refs.append(el('p','Il tratto selezionato è <Video 1>. Le immagini aggiuntive sono <Picture 1>, <Picture 2>…; gli altri video sono <Video 2> e <Video 3>.'));
 const grid=el('div','','dg-grid');refs.append(grid);let pictures=0,videos=1;
 c.refs.forEach((r,i)=>studio.asset(grid,r.kind==='image'?`Picture ${++pictures}`:`Video ${++videos}`,r,'name',r.kind,()=>c.refs.splice(i,1)));
 if(pictures<9)refs.append(button('+ Immagine reference',()=>{c.refs.push({kind:'image',name:''});studio.save();studio.render();}));
 if(videos<3)refs.append(button('+ Video reference',()=>{c.refs.push({kind:'video',name:''});studio.save();studio.render();}));
 refs.append(el('small','Massimo 9 immagini e 3 video incluso il sorgente. I video aggiuntivi devono durare 2–15 s; la somma, sorgente selezionato incluso, non può superare 15 s.'));
 const prompt=studio.section(body,'Cosa vuoi cambiare?');
 studio.field(prompt,'Istruzioni di edit',c,'prompt',{multi:true,rows:7,hint:'Descrivi la modifica e il ruolo delle reference. Il sorgente viene inserito automaticamente come Video 1.'});
 studio.field(prompt,'Seed',c,'seed',{type:'number',min:0,max:9007199254740990,step:1});
 const anchors=studio.field(prompt,'Mantieni i fotogrammi ai due estremi come guida',e,'anchor_edges',{type:'checkbox',hint:e.mask?.enabled?'Con maschera attiva gli estremi non vengono forzati: anche lì può essere richiesta una modifica.':'Aiuta il raccordo. Disattiva se vuoi modificare anche il primo e l’ultimo fotogramma.'});anchors.disabled=!!e.mask?.enabled;
 studio.field(prompt,'Raccordo con l’originale · secondi per lato',e,'fade',{type:'number',min:0,max:.5,step:.025,hint:'Sfumatura dentro la selezione. 0 = taglio netto. Una sfumatura troppo lunga può creare doppie immagini.'});
 studio.loras(prompt,c.common_loras,'LoRA per questo edit');
 const advanced=el('details','','dg-card');advanced.append(el('summary','Modelli e campionamento personalizzato'));body.append(advanced);
 studio.field(advanced,'Checkpoint Ref2VA',c.models,'ref2v',{options:['',...studio.catalog.models]});
 for(const [key,label,options]of[['clip','Text encoder',studio.catalog.clip],['vae','Video VAE',studio.catalog.vae],['audio','Audio VAE',studio.catalog.vae]])studio.field(advanced,label,c.models,key,{options});
 studio.sampleFields(advanced,e);
 studio.field(advanced,'Anteprima durante il calcolo',c.preview,'enabled',{type:'checkbox'});
 advanced.append(el('p','Provini alla dimensione scelta, poi sviluppo del provino approvato alla dimensione originale. Eventuali bordi per allineare H3 a 32 px vengono rimossi. Il sorgente può richiedere molta VRAM alla sua risoluzione originale.'));
 const trials=studio.section(body,'Provini edit · velocità e varianti');
 studio.field(trials,'Velocità dei provini',e,'trial_mode',{options:[['fast','Rapido · Turbo Ref2Video · 4 passaggi'],['same','Personalizzato · parametri avanzati']],hint:'Il rapido usa la LoRA Turbo Ref2Video installata. Il campionamento alla dimensione originale si sceglie nella scheda del provino.'});
 studio.field(trials,'Dimensione dei provini · lato lungo',e,'trial_edge',{options:[[256,'256 px · più leggero'],[384,'384 px'],[512,'512 px']],change:()=>studio.render()});
 studio.field(trials,'Anteprima durante il calcolo dei provini',e,'trial_live_preview',{type:'checkbox',hint:'Disattivata per velocizzare i provini. Il video completo del provino compare appena pronto.'});
 studio.field(trials,'Confronta',c,'exploration',{options:[['seeds','Seed diversi · stesso prompt'],['prompts','Prompt diversi · stesso seed']],change:()=>studio.render()});
 if(c.exploration==='seeds')studio.field(trials,'Numero di provini',c,'count',{type:'number',min:1,max:10,step:1});
 else{
  c.variants.forEach((variant,i)=>{const row=studio.section(trials,`Variante prompt ${i+1}`);studio.field(row,'Istruzioni aggiuntive',variant,'text',{multi:true,rows:4});
   if(c.variants.length>1)row.append(button('Rimuovi variante',()=>{c.variants.splice(i,1);studio.save();studio.render();}));
  });
  if(c.variants.length<10)trials.append(button('+ Variante prompt',()=>{c.variants.push({text:'',loras:[]});studio.save();studio.render();}));
 }
 trials.append(el('p',`I provini elaborano solo la selezione fino a ${e.trial_edge} px. In modalità rapida il primo caricamento e la prima preparazione restano necessari; i seed successivi riusano la preparazione comune. Scegli un provino per rigenerarlo alla dimensione originale con lo stesso prompt, seed e maschera.`));
 const go=button(`Genera provini edit a ${e.trial_edge} px`,()=>studio.queue('draft'));go.className='dg-primary';go.dataset.queue='';body.append(go);
 body.append(el('p','I provini sono senza audio. Il video completo conserva l’audio originale. La maschera limita la ricomposizione: nero originale, bianco generato.'));

}

export function renderEditTrials(studio,body){
 if(studio.pending||studio.previewData)studio.live(body);
 const items=studio.data.edit_trials||[];
 if(!items.length){body.append(el('p','Qui appariranno i provini edit a 512 px.'));return;}
 const selected=items.find(x=>x.id===studio.editTrialId)||items.at(-1);studio.editTrialId=selected.id;
 const versions=studio.section(body,'Provini edit disponibili');
 for(const [i,item]of items.entries()){
  const choose=button(`Provino ${i+1} · seed ${item.seed}`,()=>{studio.editTrialId=item.id;studio.editComparePosition=null;studio.render();});
  if(item.id===selected.id)choose.className='is-active';versions.append(choose);
 }
 const card=studio.section(body,`${selected.label} · ${selected.width} × ${selected.height}`);
 card.append(el('p',`Seed ${selected.seed} · selezione ${clock(selected.selection.start)} → ${clock(selected.selection.end)}`));
 if(selected.sampling)card.append(el('small',`${selected.sampling.steps} passaggi${selected.sampling.turbo?' · Turbo':''}${selected.elapsed_seconds!=null?' · '+selected.elapsed_seconds.toFixed(1)+' s':''}${selected.prepared_reused?' · preparazione riutilizzata':''}`));
 if(selected.timing_repaired)card.append(el('p','Fotogrammi recuperati dai latenti salvati. Il confronto usa l’anteprima ricostruita da quei dati, senza una nuova generazione.'));
 else if(selected.timing_version!==2)card.append(el('small',selected.latent?'Questo provino precedente verrà recuperato dai latenti salvati per correggere la fluidità, senza rilanciare MiniMax.':'Questo vecchio provino non contiene i dati necessari al recupero dei fotogrammi: genera un nuovo provino.'));
 const mask=selected.config.edit.mask;if(mask?.enabled)card.append(el('small',`Maschera del provino: ${mask.source} · generazione: espansione ${mask.grow} px · feather ${mask.feather} px`));
 const prompt=el('details');prompt.append(el('summary','Prompt del provino'),el('pre',selected.prompt));card.append(prompt);
 studio.editCompare=new EditComparison(studio,card,selected);
 card.append(el('p',`Scelto per il finale: ${selected.label} · seed ${selected.seed}`));
 studio.config.edit.final_mode ||= 'match';studio.config.edit.final_steps ??= 20;
 studio.config.edit.final_method ||= 'preserve';studio.config.edit.final_denoise ??= .25;
 studio.field(card,'Come preparare il finale',studio.config.edit,'final_method',{options:[['preserve','Mantieni edit · ingrandisci senza rigenerare'],['guided','Sviluppa con H3 · può cambiare l’edit'],['regenerate','Nuova generazione dal sorgente']],change:()=>studio.render(),hint:'Mantieni edit è predefinito: ingrandisce il risultato approvato senza sintetizzare nuovo dettaglio. Fuori dalla maschera usa il sorgente originale. Sviluppa con H3 parte dal provino, ma può aggiungere artefatti o cambiarne l’aspetto.'});
 const actual=selected.sampling||selected.config.edit;
 if(mask?.enabled){
  studio.config.edit.mask??={};compositeControls(studio,card,studio.config.edit.mask);
  card.append(el('small','Il video maschera resta quello salvato nel provino. Queste regolazioni del montaggio si possono cambiare anche scegliendo Mantieni edit, senza una nuova generazione.'));
 }
 if(studio.config.edit.final_method!=='preserve'){
 studio.config.edit.final_resolution ||= 'native';
 studio.field(card,'Risoluzione di calcolo H3',studio.config.edit,'final_resolution',{options:[['native','Nativa H3 · fino a 768 px sul lato corto'],['trial',`Come il provino · ${selected.width} × ${selected.height}`],['source','Dimensione originale · sperimentale']],hint:'L’export resta alla dimensione originale. Il calcolo nativo resta nel regime documentato di H3; la zona generata viene adattata al sorgente sotto la maschera. Il calcolo diretto alla dimensione originale può ignorare la modifica.'});
 studio.field(card,'Campionamento del passaggio H3',studio.config.edit,'final_mode',{options:[['match',`Come il provino scelto · ${actual.turbo?'Turbo':'standard'} · ${actual.steps} passaggi`],['turbo','Turbo Ref2Video · 4 passaggi'],['standard','Standard · senza Turbo']],change:()=>studio.render(),hint:'Questa scelta vale anche per un provino già generato. Prompt, seed, sorgente, reference e maschera restano quelli del provino scelto.'});
 if(studio.config.edit.final_mode==='standard')studio.field(card,'Passaggi del finale standard',studio.config.edit,'final_steps',{type:'number',min:1,max:100,step:1});
 if(studio.config.edit.final_method==='guided'){
  studio.field(card,'Intensità del raffinamento',studio.config.edit,'final_denoise',{type:'number',min:.01,max:1,step:.05,hint:'0,25 predefinito. Valori più alti danno più libertà al modello e possono cambiare il risultato.'});
  card.append(el('small',selected.latent?'Lo sviluppo trasferisce i latenti salvati del provino e mantiene la maschera.':'Questo provino precedente non ha latenti salvati: lo sviluppo codifica il suo video approvato. Il contenuto può cambiare durante il raffinamento.'));
 }
 }
 studio.field(card,'Cartella del finale · vuoto = cartella output Comfy',studio.config.edit,'final_output_dir',{hint:'Il finale viene copiato qui anche quando scegli un provino mentre gli altri sono ancora in calcolo.'});
 card.append(button('Scegli cartella del finale…',()=>studio.browseFolders('edit')));
 const finish=button('Prepara questo provino alla dimensione originale',()=>studio.useEditTrial(selected.id));finish.className='dg-primary';finish.dataset.editFinish=selected.id;card.append(finish);
 card.append(el('small','Puoi scegliere appena un provino è pronto: il calcolo del provino in corso viene fermato al prossimo punto di controllo e gli altri vengono saltati. Prompt, seed e maschera restano quelli salvati nel provino.'));
}

export function renderEditResults(studio,body){
 if(studio.pending||studio.previewData)studio.live(body);
 if(studio.pending)body.append(el('p','Nuova lavorazione ancora in corso. I video salvati qui sotto appartengono alle lavorazioni precedenti.'));
 const items=studio.data.edits||[];
 if(!items.length){body.append(el('p','Qui apparirà il video completo con il tratto già sostituito.'));return;}
 const selected=items.find(x=>x.id===studio.editResultId)||items.at(-1);studio.editResultId=selected.id;
 const controls=studio.section(body,studio.pending?'Risultati precedenti salvati':'Risultati disponibili');
 for(const [i,item]of items.entries()){
  const origin=items[i].origin_trial_label||studio.data.edit_trials?.find(x=>x.id===item.trial)?.label||'provino precedente';
  const choose=button(`Versione ${i+1} · da ${origin} · seed ${item.seed}`,()=>{studio.editResultId=item.id;studio.render();});
  if(item.id===selected.id)choose.className='is-active';controls.append(choose);
 }
 const card=studio.section(body,'Video completo salvato · confronto sincronizzato');
 const origin=selected.origin_trial_label||studio.data.edit_trials?.find(x=>x.id===selected.trial)?.label||'provino precedente';
 card.append(el('p',`Risultato da ${origin} · seed ${selected.seed}${selected.sampling?' · '+(selected.sampling.turbo?'Turbo':'standard')+' · '+selected.sampling.steps+' passaggi':''}`));
 if(selected.mask_report?.enabled)card.append(el('small','Maschera video verificata nel campionamento e applicata alla ricomposizione.'));
 if(selected.development)card.append(el('p',selected.development.method==='preserve'?'Edit del provino mantenuto · ingrandimento senza nuova generazione':selected.development.method==='guided'?'Sviluppato dal provino approvato':'Nuova generazione dal sorgente'));
 if(selected.export_encoding==='lossless_h264')card.append(el('p','Export senza perdita · fotogrammi originali e campioni colore protetti conservati. Il file può essere più grande.'));
 else card.append(el('p','Export precedente: non include le correzioni della fluidità e del salvataggio senza perdita. Prepara nuovamente il finale dal provino.'));
 if(selected.composite_mask_settings){const m=selected.composite_mask_settings;card.append(el('small',`Montaggio: ${m.composite_mode==='generation'?'area H3':'maschera separata'} · espansione ${m.grow} px · feather ${m.feather} px`));}
 if(selected.generation_width)card.append(el('small',`Calcolo H3: ${selected.generation_width} × ${selected.generation_height} · export: ${selected.width} × ${selected.height}`));
 studio.editCompare=new EditComparison(studio,card,selected);
 card.append(el('small',selected.saved_path));
 if(selected.export_error)card.append(el('p','Il video completo è conservato nella sessione. La copia nella cartella scelta non è riuscita: '+selected.export_error));
 card.append(button('Apri cartella del video salvato',async()=>{try{await studio.request('/dogma/h3/v2/open-folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:studio.config.session,id:selected.id})});}catch(e){studio.fail(e.message);}}));
 const copy=button('Copia questo finale nella cartella scelta',async()=>{if(copy.disabled)return;copy.disabled=true;try{const result=await studio.request('/dogma/h3/v2/edit/export-copy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:studio.config.session,id:selected.id,output_dir:studio.config.edit.final_output_dir||studio.config.output_dir})});for(const item of studio.data.edits||[])if(item.id===result.id){item.saved_path=result.saved_path;delete item.export_error;}studio.data.status='done';studio.data.message='Video completo copiato nella cartella scelta.';studio.render();}catch(e){studio.fail(e.message);}finally{copy.disabled=false;}});copy.disabled=studio.pending;card.append(copy);
 card.append(el('small','La copia usa il video già completato, senza ricalcolarlo. Destinazione: '+(studio.config.edit.final_output_dir||studio.config.output_dir||'cartella output Comfy')));
 card.append(button('Cambia cartella di destinazione…',()=>studio.browseFolders('edit')));
 const link=el('a','Scarica video completo');link.href=viewURL(selected.video);link.download=selected.video.filename;card.append(link);
 card.append(button('Torna alla selezione',()=>{studio.page='prepare';studio.render();}));
}

class EditTimeline{
 constructor(studio,root,config){
  this.studio=studio;this.root=root;this.config=config;this.closed=false;this.ready=false;this.error='';this.inputError='';this.abort=new AbortController();
  root.append(el('p','Lettura dei fotogrammi e preparazione della timeline…'));
  this.init().catch(e=>{if(!this.closed&&e.name!=='AbortError'){this.error=e.message;root.replaceChildren(el('p',e.message),button('Ricarica timeline',()=>{this.destroy();root.replaceChildren();studio.editTimeline=new EditTimeline(studio,root,config);}));studio.editMeta=null;}});
 }
 destroy(){if(this.video)this.studio.editPosition={source:this.config.source,time:this.video.currentTime,viewStart:this.viewStart,span:this.span};this.closed=true;this.ready=false;this.abort.abort();clearTimeout(this.thumbTimer);cancelAnimationFrame(this.seekRAF);cancelAnimationFrame(this.playRAF);this.preview?.destroy();}
 async init(){
  const studio=this.studio,config=this.config;
  const base=await this.studio.request('/dogma/h3/v2/edit/metadata?'+new URLSearchParams({name:this.config.source}),{signal:this.abort.signal});
  const others=this.studio.config.refs.filter(r=>r.kind==='video'&&r.name);
  const refs=others.length?await Promise.all(others.map(r=>this.studio.request('/dogma/h3/v2/edit/metadata?'+new URLSearchParams({name:r.name}),{signal:this.abort.signal}))):[];
  if(refs.some(r=>r.duration<2||r.duration>15))throw new Error('Ogni video reference aggiuntivo deve durare da 2 a 15 secondi.');
  const budget=15-refs.reduce((sum,r)=>sum+r.duration,0),minimum=Math.max(5,...refs.map(r=>Math.floor((r.duration*24-5)/17)*17+5));
  const m={...base,generation_frames:Array.from({length:21},(_,i)=>5+17*i).filter(n=>n>=minimum&&n/24<=budget+1e-8)};
  if(this.closed)return;
  if(!m.generation_frames.length)throw new Error('Le reference video non lasciano spazio per la selezione: accorciale o rimuovile.');
  this.meta=m;this.studio.editMeta={...base,source:this.config.source};
  Object.assign(this.config,snapSelection(this.config.start,this.config.end,m));this.studio.save();
  this.viewStart=0;this.span=Math.min(m.duration,Math.max(20,this.config.end-this.config.start+6));
  this.viewStart=clamp(this.config.start-2,0,m.duration-this.span);
  const saved=studio.editPosition?.source===this.config.source?studio.editPosition:null;
  if(saved){this.span=Math.min(m.duration,saved.span);this.viewStart=clamp(saved.viewStart,0,m.duration-this.span);}
  this.root.replaceChildren();
  this.preview=mediaPreview(inputFile(this.config.source),{className:'dg-edit-player'});
  const v=this.video=this.preview.media;this.root.append(this.preview.root);
  v.loop=studio.editLoop!==false;
  this.info=el('p');this.root.append(this.info);
  const controls=el('div','','dg-edit-controls');
  const loopLabel=el('label','Ripeti in loop'),loop=el('input');loop.type='checkbox';loop.checked=studio.editLoop!==false;loop.onchange=()=>{studio.editLoop=loop.checked;v.loop=loop.checked;};loopLabel.prepend(loop);controls.append(loopLabel);
  controls.append(button('Riproduci selezione',()=>{if(!this.commitInputs())return;cancelAnimationFrame(this.seekRAF);this.seekRAF=null;v.currentTime=this.config.start;this.playingSelection=true;v.play().catch(()=>{this.playingSelection=false;});}),button('Pausa',()=>{this.playingSelection=false;v.pause();}));
  controls.append(button('−1 fotogramma',()=>this.seek(stepTime(m,v.currentTime,-1))),button('+1 fotogramma',()=>this.seek(stepTime(m,v.currentTime,1))));
  controls.append(button('Inizia la selezione da qui',()=>{const t=frameTime(m,Math.min(frameCount(m)-1,frameIndex(m,v.currentTime))),d=this.config.end-this.config.start;this.select(Math.min(t,m.duration-d),Math.min(t+d,m.duration),'end');}));
  controls.append(button('− Zoom',()=>this.zoom(2)),button('+ Zoom',()=>this.zoom(.5)),button('Tutto il video',()=>{this.span=m.duration;this.viewStart=0;this.paint(true);}));
  this.root.append(controls);
  const overviewLabel=el('label','Scorri nel video completo','dg-field');
  const overview=this.overview=el('input');overview.type='range';overview.min=0;overview.max=m.duration;overview.step=1/m.fps;
  overview.setAttribute('aria-label','Posizione nel video completo');
  overview.oninput=()=>{const t=Number(overview.value);this.viewStart=clamp(t-this.span/2,0,m.duration-this.span);this.seek(t);this.paint(true);};
  overviewLabel.append(overview);this.root.append(overviewLabel);
  const track=this.track=el('div','','dg-edit-track');track.tabIndex=0;track.setAttribute('aria-label','Timeline della selezione');
  this.thumbs=el('div','','dg-edit-thumbs');track.append(this.thumbs);
  this.band=el('div','','dg-edit-selection');this.band.title='Trascina per spostare tutto l’intervallo';track.append(this.band);
  this.left=button('❮',()=>{});this.right=button('❯',()=>{});
  for(const [h,side,label]of[[this.left,'start','Inizio selezione'],[this.right,'end','Fine selezione']]){
   h.className='dg-edit-handle';h.setAttribute('role','slider');h.setAttribute('aria-label',label);h.title=label;
   h.addEventListener('pointerdown',e=>this.drag(e,side),{signal:this.abort.signal});
   h.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();
    const delta=event.key==='ArrowLeft'?-1:1;this.select(side==='start'?stepTime(m,this.config.start,delta):this.config.start,side==='end'?frameTime(m,clamp(frameIndex(m,this.config.end)+delta,1,frameCount(m))):this.config.end,side);});
   track.append(h);
  }
  this.band.addEventListener('pointerdown',e=>this.drag(e,'move'),{signal:this.abort.signal});
  track.addEventListener('pointerdown',event=>{if(event.target===track||this.thumbs.contains(event.target))this.seek(this.timeAt(event.clientX));},{signal:this.abort.signal});
  this.playhead=el('div','','dg-edit-playhead');track.append(this.playhead);this.root.append(track);
  this.scale=el('div','','dg-edit-scale');this.root.append(this.scale);
  const times=el('div','','dg-grid');this.root.append(times);
  const owner=this;
  this.startInput=studioField('Da · secondi','start');this.endInput=studioField('A · secondi','end');
  function studioField(label,key){
   const wrap=el('label',label,'dg-field'),i=el('input');i.type='text';i.inputMode='decimal';wrap.append(i);times.append(wrap);
   i.oninput=()=>{owner.inputsDirty=true;i.setCustomValidity('');owner.studio.editInputDraft={source:owner.config.source,start:owner.startInput.value,end:owner.endInput.value};};
   i.onchange=()=>owner.commitInputs();
   i.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();owner.commitInputs();}};
   return i;
  }
  const draft=studio.editInputDraft;if(draft?.source===this.config.source){this.inputsDirty=true;this.startInput.value=draft.start;this.endInput.value=draft.end;}
  this.inputMessage=el('small');this.inputMessage.setAttribute('role','status');this.root.append(this.inputMessage);
  this.root.append(el('small',`Trascina i bordi o inserisci i secondi, anche con la virgola. Selezione libera fino a ${(m.generation_frames.at(-1)/24).toFixed(2)} s, con precisione di un fotogramma e senza minimo di 4 secondi. H3 calcola i fotogrammi aggiuntivi necessari; nell’export viene sostituito solo l’intervallo scelto.`));
  v.addEventListener('timeupdate',()=>{
   if(this.playingSelection&&(v.currentTime>=this.config.end||v.currentTime<this.config.start)){if(studio.editLoop!==false){v.currentTime=this.config.start;v.play().catch(()=>{});}else{v.pause();this.playingSelection=false;}}
   this.playhead.style.left=clamp((v.currentTime-this.viewStart)/this.span*100,0,100)+'%';this.overview.value=v.currentTime;
  },{signal:this.abort.signal});
  v.addEventListener('play',()=>{
   const tick=()=>{if(this.closed||v.paused)return;if(this.playingSelection&&v.currentTime>=this.config.end){if(studio.editLoop!==false){v.currentTime=this.config.start;}else{this.seek(stepTime(m,this.config.end,-1));return;}}this.playRAF=requestAnimationFrame(tick);};
   cancelAnimationFrame(this.playRAF);tick();
  },{signal:this.abort.signal});
  v.addEventListener('pause',()=>cancelAnimationFrame(this.playRAF),{signal:this.abort.signal});
  v.addEventListener('loadedmetadata',()=>this.seek(saved?.time??this.config.start),{once:true,signal:this.abort.signal});
  this.paint(true);this.ready=true;
 }
 zoom(factor){const center=(this.config.start+this.config.end)/2;this.span=clamp(this.span*factor,Math.min(.25,this.meta.duration),this.meta.duration);this.viewStart=clamp(center-this.span/2,0,this.meta.duration-this.span);this.paint(true);}
 timeAt(x){const r=this.track.getBoundingClientRect();return clamp(this.viewStart+(x-r.left)/r.width*this.span,0,this.meta.duration);}
 seek(t){this.seekTarget=frameTime(this.meta,Math.min(frameCount(this.meta)-1,frameIndex(this.meta,t)));if(this.seekRAF)return;
  this.seekRAF=requestAnimationFrame(()=>{this.seekRAF=null;if(this.closed)return;this.video.pause();this.playingSelection=false;this.video.currentTime=this.seekTarget;});}
 commitInputs(){
  if(!this.ready){this.inputError=this.error||'Attendi la preparazione della timeline.';return false;}
  let value;
  try{value=parseSelection(this.inputsDirty?this.startInput.value:String(this.config.start),this.inputsDirty?this.endInput.value:String(this.config.end),this.meta);}
  catch(e){this.inputError=e.message;this.inputMessage.textContent=e.message;this.inputsDirty=true;return false;}
  this.inputError='';this.inputMessage.textContent='';
  if(!this.inputsDirty)return true;
  Object.assign(this.config,value);this.studio.editInputDraft=null;this.inputsDirty=false;this.studio.save();this.paint(false);this.seek(this.config.start);return true;
 }
 select(a,b,side){
  const value=snapSelection(a,b,this.meta,side);
  if(value.end-value.start>this.meta.generation_frames.at(-1)/24+1e-8){this.inputMessage.textContent='La selezione supera la durata disponibile con queste reference.';return;}
  Object.assign(this.config,value);this.studio.editInputDraft=null;this.inputsDirty=false;this.inputError='';this.inputMessage.textContent='';this.studio.save();this.paint(false);this.seek(side==='start'?this.config.start:stepTime(this.meta,this.config.end,-1));
 }
 drag(event,side){event.preventDefault();event.stopPropagation();const target=event.currentTarget;target.setPointerCapture(event.pointerId);
  const initial={a:this.config.start,b:this.config.end,t:this.timeAt(event.clientX)};
  const move=ev=>{if(side==='move'){const delta=clamp(this.timeAt(ev.clientX)-initial.t,-initial.a,this.meta.duration-initial.b);this.select(initial.a+delta,initial.b+delta,'end');}
   else this.select(side==='start'?this.timeAt(ev.clientX):this.config.start,side==='end'?this.timeAt(ev.clientX):this.config.end,side);};
  const end=()=>{target.removeEventListener('pointermove',move);target.removeEventListener('pointerup',end);target.removeEventListener('pointercancel',end);};
  target.addEventListener('pointermove',move);target.addEventListener('pointerup',end);target.addEventListener('pointercancel',end);
 }
 paint(thumbnails){
  const c=this.config,m=this.meta,pct=t=>clamp((t-this.viewStart)/this.span*100,0,100);
  const a=pct(c.start),b=pct(c.end);this.band.style.left=a+'%';this.band.style.width=Math.max(0,b-a)+'%';
  this.left.style.left=a+'%';this.right.style.left=b+'%';
  this.left.hidden=c.start<this.viewStart||c.start>this.viewStart+this.span;this.right.hidden=c.end<this.viewStart||c.end>this.viewStart+this.span;
  for(const [h,t]of[[this.left,c.start],[this.right,c.end]]){h.setAttribute('aria-valuenow',t.toFixed(4));h.setAttribute('aria-valuemin','0');h.setAttribute('aria-valuemax',m.duration);h.setAttribute('aria-valuetext',clock(t));}
  if(!this.inputsDirty){this.startInput.value=c.start.toFixed(6);this.endInput.value=c.end.toFixed(6);}
  this.info.textContent=`${m.width} × ${m.height} · ${m.fps.toFixed(3)} fps · ${clock(c.start)} → ${clock(c.end)} · selezione ${(c.end-c.start).toFixed(3)} s`;
  this.scale.replaceChildren(el('span',clock(this.viewStart)),el('span',clock(this.viewStart+this.span)));
  this.overview.value=this.video.currentTime;
  if(thumbnails){clearTimeout(this.thumbTimer);this.thumbTimer=setTimeout(()=>{if(this.closed)return;this.thumbs.replaceChildren();for(let i=0;i<8;i++){
   const t=Math.min(m.duration-1/m.fps,this.viewStart+(i+.5)*this.span/8),img=el('img');img.alt=clock(t);img.loading='lazy';img.draggable=false;
   img.src=url('/dogma/h3/v2/edit/thumbnail',{name:c.source,time:t});this.thumbs.append(img);
  }},180);}
 }
}

