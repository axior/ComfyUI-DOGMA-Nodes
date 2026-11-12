import { api } from '../../scripts/api.js';

const el=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
const button=(text,fn)=>{const e=el('button',text);e.type='button';e.onclick=fn;return e;};
const url=(path,params)=>api.apiURL(path+'?'+new URLSearchParams(params));
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
export const editCounts=(fps,frames=Array.from({length:15},(_,i)=>107+17*i))=>frames.map(n=>Math.floor(n*fps/24+1e-8));
export function snapSelection(start,end,meta,side='end'){
 const fps=meta.fps,total=Math.floor(meta.duration*fps+1e-6),counts=editCounts(fps,meta.generation_frames).filter(n=>n<=total);
 if(!counts.length)throw new Error('Nessuna durata H3 disponibile: serve un sorgente di almeno circa 4,46 s e un totale video reference entro 15 s.');
 let a=Math.round(start*fps),b=Math.round(end*fps);
 const wanted=Math.max(0,b-a),n=counts.reduce((best,x)=>Math.abs(x-wanted)<Math.abs(best-wanted)?x:best,counts[0]);
 if(side==='start'){b=clamp(b,n,total);a=b-n;}else{a=clamp(a,0,total-n);b=a+n;}
 return {start:a/fps,end:b/fps};
}
export const clock=t=>{const m=Math.floor(t/60),s=t-m*60;return `${String(m).padStart(2,'0')}:${s.toFixed(3).padStart(6,'0')}`;};

export function renderEditor(studio,body){
 const c=studio.config,e=c.edit;
 const section=studio.section(body,'Video originale · scegli il tratto da modificare');
 const upload=el('input');upload.type='file';upload.accept='video/*';upload.hidden=true;
 const load=button(e.source?'Cambia video':'Carica video',()=>upload.click());
 const uploadStatus=el('small');
 upload.onchange=async()=>{
  const file=upload.files?.[0];if(!file)return;
  load.disabled=true;uploadStatus.textContent='Caricamento del video sul server…';
  try{
   const data=new FormData();data.append('image',file);data.append('type','input');data.append('subfolder','DOGMA_DIRECTOR');
   const r=await studio.request('/upload/image',{method:'POST',body:data});
   e.source=(r.subfolder?r.subfolder+'/':'')+r.name;e.start=0;e.end=107/24;
   studio.editMeta=null;studio.save();studio.render();
  }catch(err){if(err.name!=='AbortError')studio.fail(err.message);}
  finally{load.disabled=false;uploadStatus.textContent='';}
 };
 section.append(upload,load,uploadStatus);
 if(e.source){
  section.append(el('small',e.source));
  const timeline=el('div','','dg-edit-panel');section.append(timeline);
  studio.editTimeline=new EditTimeline(studio,timeline,e);
 }
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
 studio.field(prompt,'Mantieni i fotogrammi ai due estremi come guida',e,'anchor_edges',{type:'checkbox',hint:'Aiuta il raccordo. Disattiva se vuoi modificare anche il primo e l’ultimo fotogramma.'});
 studio.field(prompt,'Raccordo con l’originale · secondi per lato',e,'fade',{type:'number',min:0,max:.5,step:.025,hint:'Sfumatura dentro la selezione. 0 = taglio netto. Una sfumatura troppo lunga può creare doppie immagini.'});
 studio.loras(prompt,c.common_loras,'LoRA per questo edit');
 const advanced=el('details','','dg-card');advanced.append(el('summary','Qualità edit · modello e campionamento'));body.append(advanced);
 studio.field(advanced,'Checkpoint Ref2VA',c.models,'ref2v',{options:['',...studio.catalog.models]});
 for(const [key,label,options]of[['clip','Text encoder',studio.catalog.clip],['vae','Video VAE',studio.catalog.vae],['audio','Audio VAE',studio.catalog.vae]])studio.field(advanced,label,c.models,key,{options});
 studio.sampleFields(advanced,e);
 studio.field(advanced,'Anteprima durante il calcolo',c.preview,'enabled',{type:'checkbox'});
 advanced.append(el('p','Generazione diretta alla dimensione originale, senza upscale, RIFE o sviluppo. Eventuali bordi per allineare H3 a 32 px vengono rimossi. Il sorgente può richiedere molta VRAM alla sua risoluzione originale.'));
 const go=button('Applica edit e ricomponi il video',()=>studio.queue('draft'));go.className='dg-primary';go.dataset.queue='';body.append(go);
 body.append(el('p','L’audio originale viene mantenuto. Il video completo viene ricodificato ad alta qualità; il raccordo dipende anche dalla coerenza del risultato generato.'));
}

export function renderEditResults(studio,body){
 studio.live(body);
 const items=studio.data.edits||[];
 if(!items.length){body.append(el('p','Qui apparirà il video completo con il tratto già sostituito.'));return;}
 const grid=el('div','','dg-gallery');body.append(grid);
 for(const item of [...items].reverse()){
  const card=studio.section(grid,item.label),v=el('video');v.controls=true;v.preload='metadata';v.src=url('/view',item.video);card.append(v);
  card.append(el('p',`${item.width} × ${item.height} · ${item.fps.toFixed(3)} fps · edit ${clock(item.selection.start)} → ${clock(item.selection.end)}`));
  card.append(el('small',item.saved_path));
  const link=el('a','Scarica video completo');link.href=url('/view',item.video);link.download=item.video.filename;card.append(link);
  card.append(button('Torna alla selezione',()=>{studio.page='prepare';studio.render();}));
 }
}

class EditTimeline{
 constructor(studio,root,config){
  this.studio=studio;this.root=root;this.config=config;this.closed=false;this.abort=new AbortController();
  this.init().catch(e=>{if(!this.closed&&e.name!=='AbortError'){root.replaceChildren(el('p',e.message));studio.editMeta=null;}});
 }
 destroy(){this.closed=true;this.abort.abort();clearTimeout(this.thumbTimer);cancelAnimationFrame(this.seekRAF);this.video?.pause();}
 async init(){
  const studio=this.studio,config=this.config;
  const cached=this.studio.editMeta?.source===this.config.source?this.studio.editMeta:null;
  const base=cached||await this.studio.request('/dogma/h3/v2/edit/metadata?'+new URLSearchParams({name:this.config.source}));
  const others=this.studio.config.refs.filter(r=>r.kind==='video'&&r.name);
  const refs=others.length?await Promise.all(others.map(r=>this.studio.request('/dogma/h3/v2/edit/metadata?'+new URLSearchParams({name:r.name})))):[];
  if(refs.some(r=>r.duration<2||r.duration>15))throw new Error('Ogni video reference aggiuntivo deve durare da 2 a 15 secondi.');
  const budget=15-refs.reduce((sum,r)=>sum+r.duration,0),minimum=Math.max(107,...refs.map(r=>Math.floor((r.duration*24-5)/17)*17+5));
  const m={...base,generation_frames:Array.from({length:15},(_,i)=>107+17*i).filter(n=>n>=minimum&&n/24<=budget+1e-8)};
  if(this.closed)return;
  this.meta=m;this.studio.editMeta={...base,source:this.config.source};
  Object.assign(this.config,snapSelection(this.config.start,this.config.end,m));this.studio.save();
  this.viewStart=0;this.span=Math.min(m.duration,Math.max(20,this.config.end-this.config.start+6));
  this.viewStart=clamp(this.config.start-2,0,m.duration-this.span);
  const v=this.video=el('video','','dg-edit-player');v.controls=true;v.preload='metadata';v.playsInline=true;
  v.src=url('/view',{filename:this.config.source,type:'input'});this.root.append(v);
  v.addEventListener('error',()=>this.info.textContent='Il browser non riproduce questo codec. Le miniature restano disponibili; per l’anteprima live usa un MP4 H.264.');
  this.info=el('p');this.root.append(this.info);
  const controls=el('div','','dg-edit-controls');
  controls.append(button('Riproduci selezione',()=>{v.currentTime=this.config.start;this.playingSelection=true;v.play().catch(()=>{});}),button('Pausa',()=>{this.playingSelection=false;v.pause();}));
  controls.append(button('Inizia la selezione da qui',()=>{const t=v.currentTime;this.select(t,t+this.config.end-this.config.start,'end');}));
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
    const delta=(event.key==='ArrowLeft'?-1:1)*17/24;this.select(side==='start'?this.config.start+delta:this.config.start,side==='end'?this.config.end+delta:this.config.end,side);});
   track.append(h);
  }
  this.band.addEventListener('pointerdown',e=>this.drag(e,'move'),{signal:this.abort.signal});
  track.addEventListener('pointerdown',event=>{if(event.target===track||this.thumbs.contains(event.target))this.seek(this.timeAt(event.clientX));},{signal:this.abort.signal});
  this.playhead=el('div','','dg-edit-playhead');track.append(this.playhead);this.root.append(track);
  this.scale=el('div','','dg-edit-scale');this.root.append(this.scale);
  const times=el('div','','dg-grid');this.root.append(times);
  this.startInput=studioField('Da · secondi','start');this.endInput=studioField('A · secondi','end');
  function studioField(label,key){const input=timelinePlaceholder();return input;
   function timelinePlaceholder(){
    const wrap=el('label',label,'dg-field'),i=el('input');i.type='number';i.min=0;i.max=m.duration;i.step=1/m.fps;wrap.append(i);times.append(wrap);
    i.onchange=()=>{const x=Number(i.value);if(!Number.isFinite(x))return;const c=config;
     Object.assign(c,snapSelection(key==='start'?x:c.start,key==='end'?x:c.end,m,key));
     studio.save();studio.editTimeline.paint(false);studio.editTimeline.seek(key==='start'?c.start:Math.max(c.start,c.end-1/m.fps));};return i;
   }
  }
  this.root.append(el('small',`Trascina i bordi arancioni per cambiare la durata; trascina il centro per spostare l’intervallo. Usa la barra del video completo e “Inizia la selezione da qui” per raggiungere scene lontane. Durate H3 disponibili con queste reference: ${(m.generation_frames[0]/24).toFixed(2)}–${(m.generation_frames.at(-1)/24).toFixed(2)} s, a scatti. H3 genera a 24 fps: l’export mantiene i timestamp del sorgente senza interpolazione.`));
  v.addEventListener('timeupdate',()=>{
   if(this.playingSelection&&v.currentTime>=this.config.end){v.pause();this.playingSelection=false;}
   this.playhead.style.left=clamp((v.currentTime-this.viewStart)/this.span*100,0,100)+'%';
  },{signal:this.abort.signal});
  v.addEventListener('loadedmetadata',()=>this.seek(this.config.start),{once:true,signal:this.abort.signal});
  this.paint(true);
 }
 zoom(factor){const center=(this.config.start+this.config.end)/2;this.span=clamp(this.span*factor,5,this.meta.duration);this.viewStart=clamp(center-this.span/2,0,this.meta.duration-this.span);this.paint(true);}
 timeAt(x){const r=this.track.getBoundingClientRect();return clamp(this.viewStart+(x-r.left)/r.width*this.span,0,this.meta.duration);}
 seek(t){this.seekTarget=clamp(t,0,Math.max(0,this.meta.duration-1/this.meta.fps));if(this.seekRAF)return;
  this.seekRAF=requestAnimationFrame(()=>{this.seekRAF=null;if(this.closed)return;this.video.pause();this.playingSelection=false;this.video.currentTime=this.seekTarget;});}
 select(a,b,side){Object.assign(this.config,snapSelection(a,b,this.meta,side));this.studio.save();this.paint(false);this.seek(side==='start'?this.config.start:this.config.end-1/this.meta.fps);}
 drag(event,side){event.preventDefault();event.stopPropagation();const target=event.currentTarget;target.setPointerCapture(event.pointerId);
  const initial={a:this.config.start,b:this.config.end,t:this.timeAt(event.clientX)};
  const move=ev=>{if(side==='move'){const delta=this.timeAt(ev.clientX)-initial.t;this.select(initial.a+delta,initial.b+delta,'end');}
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
  this.startInput.value=c.start.toFixed(6);this.endInput.value=c.end.toFixed(6);
  this.info.textContent=`${m.width} × ${m.height} · ${m.fps.toFixed(3)} fps · ${clock(c.start)} → ${clock(c.end)} · selezione ${(c.end-c.start).toFixed(3)} s`;
  this.scale.replaceChildren(el('span',clock(this.viewStart)),el('span',clock(this.viewStart+this.span)));
  this.overview.value=this.viewStart+this.span/2;
  if(thumbnails){clearTimeout(this.thumbTimer);this.thumbTimer=setTimeout(()=>{if(this.closed)return;this.thumbs.replaceChildren();for(let i=0;i<8;i++){
   const t=Math.min(m.duration-1/m.fps,this.viewStart+(i+.5)*this.span/8),img=el('img');img.alt=clock(t);img.loading='lazy';img.draggable=false;
   img.src=url('/dogma/h3/v2/edit/thumbnail',{name:c.source,time:t});this.thumbs.append(img);
  }},180);}
 }
}
