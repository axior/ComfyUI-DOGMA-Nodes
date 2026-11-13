import { mediaPreview } from './dogma_h3_media.js?v=studio-1-0-46';

const el=(tag,text='')=>{const e=document.createElement(tag);e.textContent=text;return e;};
export function maskKey(c){
 const e=c.edit,m=e.mask;
 return JSON.stringify([e.source,e.start,e.end,e.fade,m.enabled,m.source,Number(m.grow),Number(m.feather),Number(m.opacity),m.view]);
}

export class MaskEditor{
 constructor(studio,parent){
  this.studio=studio;this.closed=false;this.abort=new AbortController();
  const c=studio.config,e=c.edit;
  e.mask={enabled:false,source:'',grow:0,feather:0,opacity:.55,view:'overlay',...e.mask};
  const m=e.mask,root=studio.section(parent,'Maschera video · opzionale');
  root.append(el('p','Carica il tuo video bianco e nero, allineato al sorgente completo. Bianco: usa la zona generata. Nero: conserva il video originale. I grigi miscelano i due. La maschera non viene generata dal workflow.'));
  studio.field(root,'Usa la maschera video',m,'enabled',{type:'checkbox',change:()=>{studio.save();studio.render();}});
  studio.asset(root,'Video maschera caricato da te',m,'source','video',()=>{m.source='';m.enabled=false;},()=>{m.enabled=true;});
  if(!m.enabled)return;
  studio.field(root,'Espandi / contrai · pixel del sorgente',m,'grow',{type:'number',step:1,hint:'Valori positivi espandono il bianco; negativi lo contraggono. 0 mantiene il bordo.'});
  studio.field(root,'Feather · sfumatura in pixel del sorgente',m,'feather',{type:'number',min:0,step:.5,hint:'Sfumatura applicata dopo espansione o contrazione.'});
  studio.field(root,'Vista dell’anteprima',m,'view',{options:[['overlay','Video + maschera arancione'],['mask','Solo maschera elaborata'],['source','Solo video originale']]});
  studio.field(root,'Opacità overlay · solo anteprima',m,'opacity',{type:'number',min:0,max:1,step:.05});
  this.go=el('button','Prepara video overlay');this.go.type='button';this.go.onclick=()=>this.start();
  this.notice=el('p');this.notice.setAttribute('role','status');this.progress=el('progress');if(this.progress)this.progress.hidden=true;
  this.previewRoot=el('div');root.append(this.go,this.notice,this.progress,this.previewRoot);
  root.append(el('small','L’overlay usa la selezione, i bordi e il raccordo correnti. È una verifica della maschera senza avviare H3. La maschera guida sia la generazione nativa H3 sia la ricomposizione finale. Il modello usa una griglia più grossa: l’overlay mostra i bordi precisi della ricomposizione.'));
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
 show(file){this.player?.destroy();this.player=mediaPreview(file,{loop:true});this.previewRoot.replaceChildren(this.player.root);this.notice.textContent='Overlay pronto. L’arancione indica dove sarà applicato l’edit, inclusi i bordi sfumati.';}
 destroy(){if(this.closed)return;this.closed=true;clearInterval(this.watch);this.cancel();this.abort.abort();this.player?.destroy();}
}
