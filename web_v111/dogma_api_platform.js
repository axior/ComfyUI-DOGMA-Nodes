import { app } from '../../scripts/app.js';
import { api } from '../../scripts/api.js';
import { PlatformUI } from './dogma_api_ui.js?v=1.0.54';
import { ALL_FAMILIES,copy,migrateState,activeReferences,inputSpec } from './dogma_api_core.js?v=1.0.54';
const ROOT=new URL('.',import.meta.url);
const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('dogma_api_platform.css?v=1.0.54',ROOT);document.head.append(css);
let opened=null,queueLock=false;

class ComfyBridge {
 constructor(node){this.node=node;this.preview=false;this.pricingNodes=new Map();}
 get widget(){return this.node.widgets.find(w=>w.name==='config');}
 load(){const s=JSON.parse(this.widget.value||'{}');if(!s.models)throw new Error('Apri DOGMA_API_PLATFORM_V2.json.');return migrateState(s);}
 async initialize(state){
  const defaults=await (await fetch(new URL('dogma_api_defaults.json?v=1.0.54',ROOT))).json();
  for(const [key,value] of Object.entries(defaults.models))state.models[key] ||= copy(value);
  state.prompts.video ||= defaults.prompts.video;
  this.catalog=await this.request('/catalog');
  this.defs=await (await api.fetchApi('/object_info')).json();
  if(state.workspace){try{await this.workspace(state.workspace);}catch{state.workspace='';}}
  try{
   const script=[...document.querySelectorAll('script[type=module][src]')].find(x=>x.src.includes('/assets/'));
   const base=script?.src||new URL('/assets/index.js',location.href).href;
   const names=this.catalog.frontend;
   if(names.billing&&names.credits){
    const [billing,credits]=await Promise.all([import(new URL(names.billing.file,base).href),import(new URL(names.credits.file,base).href)]);
    this.billing=billing[names.billing.context]();this.nativePricing=billing[names.billing.pricing]();this.formatCredits=credits[names.credits.format];
   }
  }catch(e){console.warn('DOGMA: servizi crediti/prezzi non disponibili in questo frontend.');}
 }
 save(s){this.widget.value=JSON.stringify(s);this.node.setDirtyCanvas?.(true,true);clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>{if(this.node.graph===app.graph)app.graph.change?.();},250);}
 logo(){return new URL('dogma_api_logo.png',ROOT).href;}
 view(file){if(file?.url)return file.url;const p=new URLSearchParams(typeof file==='string'?{filename:file,type:'input'}:{filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'});return api.apiURL('/view?'+p);}
 async request(path,body){const headers={};if(this.catalog?.access?.token)headers['X-Dogma-Access']=this.catalog.access.token;if(body!==undefined)headers['Content-Type']='application/json';const response=await api.fetchApi('/dogma/api/v2'+path,{method:body===undefined?'GET':'POST',headers,...(body!==undefined?{body:JSON.stringify(body)}:{})});if(!response.ok)throw new Error((await response.text()).slice(0,800));return response.json();}
 async upload(file){const body=new FormData();body.append('image',file,file.name);body.append('type','input');body.append('subfolder','DOGMA_API');body.append('overwrite','false');const r=await api.fetchApi('/upload/image',{method:'POST',body});if(!r.ok)throw new Error('Caricamento non riuscito.');const d=await r.json();return {file:[d.subfolder,d.name].filter(Boolean).join('/'),kind:file.type.startsWith('video/')?'video':'image'};}
 async workspace(path){return this.request('/workspace',{path});}
 async chooseFolder(path){if(this.catalog?.access?.open_folder)return this.request('/choose-folder',{path});return {browse:true};}
 async folders(path){return this.request('/folders?'+new URLSearchParams({path:path||''}));}
 async library(){return (await this.request('/library')).records;}
 async previewReference(ref,settings){return this.request('/reference-preview',{file:ref.file,settings});}
 async openOutput(id,index){return this.request('/open-output',{id,index});}
 async credits(){
  if(!this.billing||!this.formatCredits)return {text:'CREDITS —',title:'Saldo non disponibile. Apri l’account Comfy.'};
  try{await this.billing.fetchBalance();const raw=this.billing.balance,b=raw&&'value' in raw?raw.value:raw;const amount=b?.effectiveBalanceMicros??b?.amountMicros;if(!Number.isFinite(amount))return {text:'ACCEDI A COMFY',title:'Accedi all’account da Comfy per vedere i crediti.'};return {text:this.formatCredits({cents:amount,locale:'it-IT',numberOptions:{minimumFractionDigits:0,maximumFractionDigits:2}})+' CREDITS LEFT',title:'Saldo dello stesso account e workspace di Comfy'};}catch{return {text:'CREDITS —',title:'Saldo temporaneamente non disponibile. Clicca per aggiornare.'};}
 }
 inputSpec(state,f,key){const m=state.models[f.key],frames=m.engine==='frames';return inputSpec(this.defs?.[frames?'ByteDance2FirstLastFrameNode':f.type],frames?m.frames:m.parameters,key);}
 price(state,f){
  if(!this.nativePricing||!this.defs)return '';
  const m=state.models[f.key],frames=f.key==='seedance'&&m.engine==='frames',type=frames?'ByteDance2FirstLastFrameNode':f.type,def=this.defs[type];if(!def)return '';
  let n=this.pricingNodes.get(type);if(!n){n={constructor:{nodeData:def},inputs:[],widgets:[],isInputConnected:i=>!!n.inputs[i]?.link};this.pricingNodes.set(type,n);}
  const refs=activeReferences(state),images=refs.filter(r=>r.kind==='image'),videos=refs.filter(r=>r.kind==='video');
  const values=frames?m.frames:m.parameters;n.widgets=Object.entries(values).map(([name,value])=>({name,value}));
  n.inputs=[];
  if(f.key==='nano'&&images.length)n.inputs.push({name:'images',link:1});
  else if(f.key==='seedance'){images.forEach((r,i)=>n.inputs.push({name:`model.reference_images.image_${i+1}`,link:1}));videos.forEach((r,i)=>n.inputs.push({name:`model.reference_videos.video_${i+1}`,link:1}));}
  else images.forEach((r,i)=>n.inputs.push({name:`${f.key==='flux'?'':'model.'}images.image_${i+1}`,link:1}));
  try{return this.nativePricing.getNodeDisplayPrice(n,new Map(Object.entries(values)))||'';}catch{return '';}
 }
 async check(state,compiled){
  this.defs=await (await api.fetchApi('/object_info')).json();const missing=[...new Set(Object.values(compiled.output).map(n=>n.class_type))].filter(type=>!this.defs[type]);if(missing.length)throw new Error('Nodi mancanti: '+missing.join(', '));
  for(const ref of activeReferences(state))for(const file of [ref.file,ref.process?.maskFile].filter(Boolean)){const r=await api.fetchApi('/view?'+new URLSearchParams({filename:file,type:'input'}),{method:'HEAD'});if(!r.ok)throw new Error('Reference assente: '+file+'. Ricaricala dal pannello.');}
 }
 async queue(compiled,batch,state){
  if(queueLock||app.processingQueue||app.queueItems?.length)throw new Error('Comfy sta già inviando una richiesta. Riprova tra un momento.');
  queueLock=true;let result=null,used=false;const workflow=copy(app.graph.serialize());workflow.extra ||= {};workflow.extra.dogma_api_batch={session:state.session,id:batch,jobs:copy(compiled.jobs)};
  const nativeBuild=app.graphToPrompt,nativeQueue=api.queuePrompt;
  const build=function(...args){if(used)return nativeBuild.apply(this,args);used=true;return Promise.resolve({workflow,output:compiled.output});};
  const capture=async function(...args){const r=await nativeQueue.apply(this,args);if(args[1]?.workflow===workflow)result=r;return r;};
  app.graphToPrompt=build;api.queuePrompt=capture;
  try{await app.queuePrompt(0,1);if(!result?.prompt_id)throw new Error('Comfy non ha accettato il batch. Controlla accesso e messaggi di Comfy.');return result.prompt_id;}
  finally{if(app.graphToPrompt===build)app.graphToPrompt=nativeBuild;if(api.queuePrompt===capture)api.queuePrompt=nativeQueue;queueLock=false;}
 }
 subscribe(handler){const controller=new AbortController();for(const name of ['execution_start','executing','executed','execution_success','execution_error','execution_interrupted','progress'])api.addEventListener(name,e=>handler(name,e.detail),{signal:controller.signal});return ()=>controller.abort();}
 async history(){const r=await api.fetchApi('/history?max_items=200');if(!r.ok)throw new Error('Cronologia non disponibile.');return r.json();}
 async cancel(id){if(typeof api.cancelJob==='function')return api.cancelJob(id);return api.interrupt(id);}
 download(state){this.save(state);const url=URL.createObjectURL(new Blob([JSON.stringify(app.graph.serialize(),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='DOGMA_API_PLATFORM_SESSION.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 close(){opened=null;}
}
app.registerExtension({name:'DOGMA.APIPlatform.2',async beforeRegisterNodeDef(type,data){if(data.name!=='DOGMAAPIPlatformV1')return;const previous=type.prototype.onNodeCreated;type.prototype.onNodeCreated=function(...args){const result=previous?.apply(this,args),config=this.widgets?.find(w=>w.name==='config');if(config){config.type='hidden';config.computeSize=()=>[0,-4];}this.addWidget('button','APRI DOGMA / API PLATFORM',null,()=>{if(opened){opened.root?.focus();return;}try{opened=new PlatformUI(new ComfyBridge(this));opened.open().catch(e=>{opened?.close();opened=null;app.ui.dialog.show(e.message);});}catch(e){opened=null;app.ui.dialog.show(e.message);}},{serialize:false});this.size=[390,110];return result;};}});
