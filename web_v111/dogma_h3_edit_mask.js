import { mediaPreview } from './dogma_h3_media.js?v=studio-1-0-50';

const el=(tag,text='')=>{const e=document.createElement(tag);e.textContent=text;return e;};
export function maskKey(c){
 const e=c.edit,m=e.mask;
 return JSON.stringify([e.source,e.start,e.end,e.fade,m]);
}

export function compositeControls(studio,root,m){
 m.composite_mode??='source';m.composite_grow??=0;m.composite_feather??=8;
 studio.field(root,'Area da applicare sull’originale',m,'composite_mode',{options:[['source','Maschera caricata · regolazioni separate'],['generation','Stessa area usata per generare']],change:()=>{studio.save();studio.render();},hint:'L’espansione per H3 può includere il telaio e il vagone. Le regolazioni separate evitano di incollare anche quelle ricostruzioni sul video originale.'});
 if(m.composite_mode==='source'){
  studio.field(root,'Espandi / contrai il montaggio · pixel del sorgente',m,'composite_grow',{type:'number',step:1,hint:'0 rispetta l’area caricata, anche se la generazione usa un’espansione maggiore.'});
  studio.field(root,'Feather del montaggio · pixel del sorgente',m,'composite_feather',{type:'number',min:0,step:1,hint:'Sfumatura verso l’interno: ammorbidisce il contorno senza estendere la modifica nelle aree nere. 0 mantiene il bordo netto.'});
 }
}

export class MaskEditor{
 constructor(studio,parent){
  this.studio=studio;this.closed=false;this.abort=new AbortController();
  const c=studio.config,e=c.edit;
  e.mask={enabled:false,source:'',grow:0,feather:0,opacity:.55,view:'overlay',preview_area:'composite',...e.mask};
  const m=e.mask,root=studio.section(parent,'Maschera video · opzionale');
  root.append(el('p','Carica il tuo video bianco e nero, allineato al sorgente completo. Bianco: usa la zona generata. Nero: conserva il video originale. I grigi miscelano i due. La maschera non viene generata dal workflow.'));
  studio.field(root,'Usa la maschera video',m,'enabled',{type:'checkbox',change:()=>{studio.save();studio.render();}});
  studio.asset(root,'Video maschera caricato da te',m,'source','video',()=>{m.source='';m.enabled=false;},()=>{m.enabled=true;});
  if(!m.enabled)return;
  studio.field(root,'Espandi / contrai per H3 · pixel del sorgente',m,'grow',{type:'number',step:1,hint:'Solo area di generazione: valori positivi espandono il bianco; negativi lo contraggono.'});
  studio.field(root,'Feather per H3 · pixel del sorgente',m,'feather',{type:'number',min:0,step:.5,hint:'Sfumatura della maschera che guida il modello.'});
  compositeControls(studio,root,m);
  studio.field(root,'Area da verificare nell’overlay',m,'preview_area',{options:[['composite','Montaggio finale sull’originale'],['generation','Area di generazione H3']]});
  studio.field(root,'Vista dell’anteprima',m,'view',{options:[['overlay','Video + maschera arancione'],['mask','Solo maschera elaborata'],['source','Solo video originale']]});
  studio.field(root,'Opacità overlay · solo anteprima',m,'opacity',{type:'number',min:0,max:1,step:.05});
  this.go=el('button','Prepara video overlay');this.go.type='button';this.go.onclick=()=>this.start();
  this.notice=el('p');this.notice.setAttribute('role','status');this.progress=el('progress');if(this.progress)this.progress.hidden=true;
  this.previewRoot=el('div');root.append(this.go,this.notice,this.progress,this.previewRoot);
  root.append(el('small','L’overlay verifica l’area scelta e il raccordo temporale senza avviare H3. Generazione e montaggio possono usare bordi diversi. Il modello usa una griglia più grossa; il montaggio rispetta la maschera nei pixel del sorgente.'));
  this.key=maskKey(c);this.refresh();
  const saved=studio.maskPreview;
  if(saved?.key===this.key)this.show(saved.file);
  this.watch=setInterval(()=>{if(maskKey(c)!==this.key){this.key=maskKey(c);this.invalidate();}this.refresh();},350);
 }
 refresh(){
  if(!this.go)return;
  const timeline=this.studio.editTimeline;
  this.go.disabled=this.busy||!this.studio.config.edit.source||!this.studio.config.edit.mask.source||this.studio.uploads>0||!timeline?.ready;
  if(!this.busy&&!timeline?.ready){this.notice.textContent=timeline?.error||'Attendi la preparazione della timeline prima di creare l’overlay.';this.readinessNotice=true;}
  else if(this.readinessNotice){this.notice.textContent='';this.readinessNotice=false;}
 }
 invalidate(){
  this.cancel();this.player?.destroy();this.player=null;this.previewRoot.replaceChildren();
  this.notice.textContent='Impostazioni o selezione cambiate. Prepara di nuovo l’overlay per vedere l’area aggiornata.';
 }
 cancel(){
  clearTimeout(this.poll);this.busy=false;if(this.progress)this.progress.hidden=true;
  if(this.job){const id=this.job;this.job=null;this.studio.request('/dogma/h3/v2/edit/mask-preview/'+id,{method:'DELETE'}).catch(()=>{});}
 }
 async start(){
  if(this.closed||this.busy)return;
  try{
   const timeline=this.studio.editTimeline;
   if(!timeline?.commitInputs())throw new Error(timeline?.inputError||'Attendi la preparazione della timeline.');
   this.cancel();this.player?.destroy();this.player=null;this.previewRoot.replaceChildren();
   const c=this.studio.config;this.key=maskKey(c);const key=this.key;
   const data={source:c.edit.source,start:c.edit.start,end:c.edit.end,fade:c.edit.fade,mask:{...c.edit.mask}};
   this.busy=true;this.refresh();this.progress.hidden=false;this.progress.removeAttribute('value');this.notice.textContent='Preparazione overlay della tua maschera…';
   const result=await this.studio.request('/dogma/h3/v2/edit/mask-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:this.abort.signal});
   if(this.closed||key!==this.key){this.studio.request('/dogma/h3/v2/edit/mask-preview/'+result.id,{method:'DELETE'}).catch(()=>{});return;}
   this.job=result.id;this.pollJob(key);
  }catch(e){if(!this.closed&&e.name!=='AbortError'){this.busy=false;if(this.progress)this.progress.hidden=true;this.notice.textContent=e.message;this.refresh();}}
 }
 async pollJob(key){
  if(this.closed||!this.job||key!==this.key)return;
  try{
   const result=await this.studio.request('/dogma/h3/v2/edit/mask-preview/'+this.job,{signal:this.abort.signal});
   if(this.closed||key!==this.key)return;
   if(result.status==='done'){
    this.job=null;this.busy=false;if(this.progress)this.progress.hidden=true;this.studio.maskPreview={key,file:result.file};this.show(result.file);this.refresh();return;
   }
   if(result.status==='error'||result.status==='cancelled')throw new Error(result.message||'Anteprima annullata.');
   if(result.total){this.progress.max=result.total;this.progress.value=result.done;this.notice.textContent=`Preparazione overlay · ${result.done}/${result.total} fotogrammi`;}
   this.poll=setTimeout(()=>this.pollJob(key),500);
  }catch(e){if(!this.closed&&e.name!=='AbortError'){this.cancel();this.notice.textContent=e.message;this.refresh();}}
 }
 show(file){this.player?.destroy();this.player=mediaPreview(file,{loop:true});this.previewRoot.replaceChildren(this.player.root);this.notice.textContent=this.studio.config.edit.mask.preview_area==='generation'?'Overlay pronto: area che guida H3. Può essere più ampia del montaggio finale.':'Overlay pronto: area applicata sull’originale, inclusi i bordi sfumati.';}
 destroy(){if(this.closed)return;this.closed=true;clearInterval(this.watch);this.cancel();this.abort.abort();this.player?.destroy();}
}
