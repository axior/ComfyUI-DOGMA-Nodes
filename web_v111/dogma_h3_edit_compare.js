import {mediaPreview,inputFile} from './dogma_h3_media.js?v=studio-1-0-46';
import {frameIndex,frameTime,frameCount,stepTime} from './dogma_h3_timing.js?v=studio-1-0-46';
const el=(tag,text='')=>{const e=document.createElement(tag);e.textContent=text;return e;};
const button=(text,fn)=>{const e=el('button',text);e.type='button';e.onclick=fn;return e;};
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
const clock=t=>`${String(Math.floor(t/60)).padStart(2,'0')}:${(t%60).toFixed(3).padStart(6,'0')}`;

export class EditComparison{
 constructor(studio,root,item){
  this.studio=studio;this.item=item;this.closed=false;this.abort=new AbortController();this.playing=false;
  const source=item.config?.edit?.source;
  if(!source){root.append(el('p','Il sorgente di questa versione non è registrato.'),mediaPreview(item.video,{loop:true}).root);return;}
  const items=[...(studio.data.edit_trials||[]),...(studio.data.edits||[])];
  const label=x=>{
   if(x.segment_only)return `${x.label} · seed ${x.seed}`;
   if(x.development?.method==='preserve')return `Finale da ${x.origin_trial_label||'provino'} · edit mantenuto · seed ${x.seed}`;
   const sampling=x.sampling||x.config?.edit;
   return `Finale da ${x.origin_trial_label||items.find(t=>t.id===x.trial)?.label||'provino precedente'} · seed ${x.seed}${sampling?' · '+(sampling.turbo?'Turbo':'standard')+' '+sampling.steps:''}`;
  };
  this.pool=[{id:'original',label:'Originale',video:inputFile(source),offset:0,end:Infinity},...items.filter(x=>x.config?.edit?.source===source).map(x=>({id:x.id,label:label(x),video:x.video,offset:x.segment_only?x.selection.start:0,end:x.segment_only?x.selection.end:x.duration}))];
  if(!this.pool.some(x=>x.id===item.id))this.pool.push({id:item.id,label:item.label,video:item.video,offset:item.segment_only?item.selection.start:0,end:item.segment_only?item.selection.end:item.duration});
  const saved=studio.editCompareChoice;
  let left=saved?.source===source?saved.left:'original',right=saved?.source===source&&saved.selected===item.id?saved.right:item.id;
  if(!this.pool.some(x=>x.id===left))left='original';if(!this.pool.some(x=>x.id===right))right=item.id;if(left===right)left=right==='original'?item.id:'original';
  studio.editCompareChoice={source,selected:item.id,left,right};
  this.left=this.pool.find(x=>x.id===left);this.right=this.pool.find(x=>x.id===right);this.key=source+'|'+left+'|'+right;
  const selectors=el('div');selectors.className='dg-grid';
  for(const [side,label,other]of[['left','Confronto A · sinistra',right],['right','Confronto B · destra',left]]){
   const wrap=el('label',label);wrap.className='dg-field';const select=el('select');
   for(const entry of this.pool){const option=el('option',entry.label);option.value=entry.id;option.disabled=entry.id===other;select.append(option);}
   select.value=side==='left'?left:right;select.onchange=()=>{studio.editCompareChoice[side]=select.value;studio.render();};wrap.append(select);selectors.append(wrap);
  }
  root.append(selectors);
  const pair=this.pair=el('div');pair.className='dg-edit-compare';pair.dataset.mode=studio.editCompareMode||'pair';
  this.original=mediaPreview(this.left.video);this.result=mediaPreview(this.right.video);
  for(const [side,entry,preview]of[['A',this.left,this.original],['B',this.right,this.result]]){
   const panel=el('div');panel.append(el('strong',entry.label),preview.root);
   if((studio.data.edit_trials||[]).some(x=>x.id===entry.id))panel.append(button(`Scegli ${side} per il finale`,()=>{studio.editTrialId=entry.id;studio.editCompareChoice.selected=entry.id;studio.page='choose';studio.render();}));
   pair.append(panel);preview.media.controls=false;preview.media.muted=true;
  }
  root.append(pair);this.a=this.original.media;this.b=this.result.media;
  const modes=el('div');modes.className='dg-edit-controls';
  for(const [mode,label]of[['pair','Affiancati'],['original','Solo A'],['result','Solo B']])modes.append(button(label,()=>{studio.editCompareMode=mode;pair.dataset.mode=mode;}));
  const actions=el('div');actions.className='dg-edit-controls';
  this.playButton=button('Riproduci edit',()=>this.play(true));this.fullButton=button('Riproduci tutto',()=>this.play(false));
  this.fullButton.hidden=this.left.offset>0||this.right.offset>0||this.left.end!==Infinity&&this.left.end<item.duration||this.right.end<item.duration;
  const loopLabel=el('label','Ripeti in loop'),loop=el('input');loop.type='checkbox';loop.checked=studio.editLoop!==false;loop.onchange=()=>{studio.editLoop=loop.checked;};loopLabel.prepend(loop);
  actions.append(this.playButton,this.fullButton,button('Pausa',()=>this.pause()),button('Vai all’edit',()=>this.seek(item.selection.start)),button('−1 fotogramma',()=>this.step(-1)),button('+1 fotogramma',()=>this.step(1)),loopLabel);
  this.slider=el('input');this.slider.type='range';this.slider.step='any';this.slider.setAttribute('aria-label','Posizione comune del confronto');this.slider.oninput=()=>this.seek(Number(this.slider.value));
  this.position=el('p');this.notice=el('small');this.notice.setAttribute('role','status');
  const sound=el('label','Audio del confronto');sound.className='dg-field';const audio=el('select');
  for(const [value,label]of[['mute','Muto'],['left','A · '+this.left.label],['right','B · '+this.right.label]]){const option=el('option',label);option.value=value;audio.append(option);}
  audio.onchange=()=>{this.a.muted=audio.value!=='left';this.b.muted=audio.value!=='right';};sound.append(audio);root.append(modes,actions,sound,this.slider,this.position,this.notice);
  const position=studio.editComparePosition;
  this.target=position?.key===this.key?position.time:item.selection.start;this.resumeWanted=position?.key===this.key&&position.playing;this.selectionOnly=position?.key===this.key?position.selectionOnly:true;
  for(const v of [this.a,this.b]){
   v.addEventListener('loadedmetadata',()=>this.restore(),{signal:this.abort.signal});
   v.addEventListener('loadeddata',()=>this.ready(),{signal:this.abort.signal});
   v.addEventListener('error',()=>{this.pause();this.ready();},{signal:this.abort.signal});
   v.addEventListener('waiting',()=>{if(this.playing&&!this.starting&&!this.restarting){this.resumeAfterBuffer=true;this.pause(false);this.notice.textContent='Attendo entrambe le anteprime…';}},{signal:this.abort.signal});
   v.addEventListener('canplay',()=>{this.ready();if(this.resumeAfterBuffer&&this.a.readyState>=3&&this.b.readyState>=3){this.resumeAfterBuffer=false;this.play(this.selectionOnly,false);}},{signal:this.abort.signal});
   v.addEventListener('ended',()=>this.reachEnd(),{signal:this.abort.signal});
  }
  this.ready();this.restore();
  studio.request('/dogma/h3/v2/edit/metadata?'+new URLSearchParams({name:source}),{signal:this.abort.signal}).then(meta=>{if(!this.closed){this.meta=meta;this.restore();}}).catch(e=>{if(!this.closed&&e.name!=='AbortError')this.notice.textContent='Tempi sorgente non disponibili. Riapri il confronto.';});
 }
 bounds(selectionOnly=false){
  const low=Math.max(this.left.offset,this.right.offset,selectionOnly?this.item.selection.start:0);
  const high=Math.min(this.a.duration+this.left.offset,this.b.duration+this.right.offset,this.left.end,this.right.end,selectionOnly?this.item.selection.end:Infinity);
  return [low,high];
 }
 ready(){
  if(this.closed||!this.a)return;
  const range=this.bounds(),ready=!!this.meta&&this.a.readyState>=2&&this.b.readyState>=2&&!this.a.error&&!this.b.error&&range[1]>range[0];
  this.playButton.disabled=this.fullButton.disabled=this.slider.disabled=!ready;
  if(ready&&this.resumeWanted){this.resumeWanted=false;this.play(this.selectionOnly,false);}
 }
 restore(){
  if(this.closed||!this.a||this.a.readyState<1||this.b.readyState<1)return;
  const [low,high]=this.bounds();if(!(high>low)){this.notice.textContent='Questi video non condividono un intervallo temporale.';this.ready();return;}
  this.target=clamp(this.target,low,high);this.slider.min=low;this.slider.max=high;
  this.a.currentTime=Math.max(0,this.target-this.left.offset);this.b.currentTime=Math.max(0,this.target-this.right.offset);this.draw();this.ready();
 }
 seek(time){
  this.pause();this.atEnd=false;const [low,high]=this.bounds();
  const last=this.meta?frameTime(this.meta,Math.max(0,frameIndex(this.meta,high)-1)):high-.001;
  this.target=clamp(this.meta?frameTime(this.meta,Math.min(frameCount(this.meta)-1,frameIndex(this.meta,time))):time,low,last);this.restore();
 }
 step(delta){if(this.meta)this.seek(stepTime(this.meta,this.a.currentTime+this.left.offset,delta));}
 async play(selectionOnly,restart=true){
  if(this.closed||!this.meta||this.a.error||this.b.error)return;
  const [low,high]=this.bounds(selectionOnly);if(!(high>low)){this.notice.textContent='Nessun tratto comune da riprodurre.';return;}
  const now=this.a.currentTime+this.left.offset;const atEnd=this.atEnd;
  this.pause();this.selectionOnly=selectionOnly;this.atEnd=false;this.resumeWanted=false;
  if(restart&&(atEnd||now<low||now>=high-.001||this.a.ended||this.b.ended)){this.target=low;this.restore();}
  const run=this.playRun;this.starting=true;this.notice.textContent='';
  if(Math.abs(this.b.currentTime+this.right.offset-this.a.currentTime-this.left.offset)>.001)this.b.currentTime=this.a.currentTime+this.left.offset-this.right.offset;
  const wait=v=>new Promise((resolve,reject)=>{
   if(v.readyState>=2&&!v.seeking){resolve();return;}
   const done=()=>{if(v.readyState>=2&&!v.seeking){clean();resolve();}};
   const cancelled=()=>{clean();reject(new Error('Confronto chiuso'));};
   const timer=setTimeout(()=>{clean();reject(new Error('Caricamento in attesa'));},15000);
   const clean=()=>{clearTimeout(timer);v.removeEventListener('seeked',done);v.removeEventListener('loadeddata',done);this.abort.signal.removeEventListener('abort',cancelled);};
   v.addEventListener('seeked',done);v.addEventListener('loadeddata',done);this.abort.signal.addEventListener('abort',cancelled,{once:true});
  });
  try{
   await Promise.all([wait(this.a),wait(this.b)]);if(this.closed||run!==this.playRun)return;
   this.playing=true;await Promise.all([this.a.play(),this.b.play()]);if(this.closed||run!==this.playRun)return;
   this.starting=false;this.tick();
  }catch(e){if(!this.closed&&run===this.playRun){this.pause();this.notice.textContent='Riproduzione non avviata: attendi il caricamento e riprova.';}}
 }
 reachEnd(){
  if(this.closed||!this.playing||this.restarting)return;
  if(this.studio.editLoop!==false){
   this.restarting=true;const selection=this.selectionOnly,[low]=this.bounds(selection);this.pause();this.target=low;this.restore();
   this.play(selection,false).finally(()=>{this.restarting=false;});
  }else{
   const [,high]=this.bounds(this.selectionOnly);this.seek(this.meta?stepTime(this.meta,high,-1):high-.001);this.atEnd=true;
  }
 }
 tick(){
  if(this.closed||!this.playing)return;
  const t=this.a.currentTime+this.left.offset,[,end]=this.bounds(this.selectionOnly);
  if(t>=end-.00001){this.reachEnd();return;}
  const drift=this.b.currentTime+this.right.offset-t,frame=1/this.meta.fps;
  if(Math.abs(drift)>Math.max(frame,.04))this.b.currentTime=t-this.right.offset;else this.b.playbackRate=clamp(1-drift*.5,.97,1.03);
  this.draw();this.raf=requestAnimationFrame(()=>this.tick());
 }
 pause(clearResume=true){this.playRun=(this.playRun||0)+1;this.starting=false;this.playing=false;if(clearResume){this.resumeAfterBuffer=false;this.resumeWanted=false;}cancelAnimationFrame(this.raf);this.a?.pause();this.b?.pause();if(this.b)this.b.playbackRate=1;}
 draw(){const t=this.a.currentTime+this.left.offset;this.target=t;this.slider.value=t;this.position.textContent=`${clock(t)} · edit ${clock(this.item.selection.start)} → ${clock(this.item.selection.end)}${this.meta?' · fotogramma '+frameIndex(this.meta,t):''}`;}
 destroy(){
  if(this.closed)return;
  if(this.a?.readyState>=2)this.studio.editComparePosition={key:this.key,time:this.a.currentTime+this.left.offset,playing:this.playing,selectionOnly:this.selectionOnly};
  this.closed=true;this.pause();this.abort.abort();this.original?.destroy();this.result?.destroy();
 }
}
