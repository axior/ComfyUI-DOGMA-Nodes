export const copy=x=>JSON.parse(JSON.stringify(x));
export const FAMILIES=[
 {key:'nano',name:'Nanobanana',short:'NB',type:'GeminiImage2Node'},
 {key:'gpt',name:'GPT Image',short:'GPT',type:'OpenAIGPTImageNodeV2'},
 {key:'flux',name:'Flux 3',short:'F3',type:'Flux3ImageNode'},
 {key:'seedream',name:'Seedream',short:'SD',type:'ByteDanceSeedreamNodeV3'},
];
export const VIDEO_FAMILIES=[{key:'seedance',name:'Seedance',short:'V',type:'ByteDance2ReferenceNodeV2'}];
export const ALL_FAMILIES=[...FAMILIES,...VIDEO_FAMILIES];
export const families=s=>s.mode==='video'?VIDEO_FAMILIES:FAMILIES;
export const safeName=s=>String(s||'').trim().replace(/[^\p{L}\p{N}_.-]+/gu,'_').replace(/^\.+/,'').slice(0,100);
export function inputSpec(def,values,name){
 const parts=name.split('.');let inputs=def?.input;
 for(let i=0;i<parts.length;i++){
  const spec=inputs?.required?.[parts[i]]||inputs?.optional?.[parts[i]];if(!spec)return null;
  if(i===parts.length-1)return spec;
  if(spec[0]==='COMFY_DYNAMICCOMBO_V3'){const key=values[parts.slice(0,i+1).join('.')];inputs=spec[1].options.find(o=>o.key===key)?.inputs;}else return null;
 }
 return null;
}
export function viewParameters(file){
 if(typeof file!=='string')return {filename:file.filename,subfolder:file.subfolder||'',type:file.type||'output'};
 const parts=file.replaceAll('\\','/').split('/');return {filename:parts.pop(),subfolder:parts.join('/'),type:'input'};
}
export function choicesFor(spec){if(!spec)return null;if(Array.isArray(spec[0]))return spec[0];if(spec[0]==='COMBO')return spec[1].options;if(spec[0]==='COMFY_DYNAMICCOMBO_V3')return spec[1].options.map(o=>o.key);return null;}
export function parameterSpecs(def,values){
 const result={};const walk=(inputs,prefix='')=>{for(const [key,spec] of Object.entries({...inputs?.required,...inputs?.optional})){
  const name=prefix+key;const choices=choicesFor(spec);
  if(choices||['INT','FLOAT','BOOLEAN','STRING'].includes(spec[0]))result[name]=spec;
  if(spec[0]==='COMFY_DYNAMICCOMBO_V3')walk(spec[1].options.find(o=>o.key===values[name])?.inputs,name+'.');
 }};walk(def?.input);return result;
}
export function modelValues(def,values){
 const specs=parameterSpecs(def,values),next={};for(const [key,spec] of Object.entries(specs)){
  const choices=choicesFor(spec),value=values[key];next[key]=value!==undefined&&(!choices||choices.includes(value))?value:spec[1]?.default??choices?.[0]??(spec[0]==='BOOLEAN'?false:spec[0]==='STRING'?'':0);
 }return next;
}
export function sortedChoices(key,values){
 const list=[...new Set(values.map(String))];if(!/resolution|size_preset|size$/.test(key))return list;
 const score=v=>{if(key==='model.size_preset'){const tier=v.match(/([\d.]+)K/i);return tier?+tier[1]:Infinity;}const dims=v.match(/(\d+)x(\d+)/);if(dims)return +dims[1]*+dims[2];const k=v.match(/([\d.]+)\s*[kK]/);if(k)return +k[1]*1000;const p=v.match(/(\d+)p/i);if(p)return +p[1];return Infinity;};return list.sort((a,b)=>score(a)-score(b));
}
export function todayCode(){const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Rome',day:'2-digit',month:'2-digit',year:'2-digit'}).formatToParts(new Date());return ['day','month','year'].map(k=>parts.find(p=>p.type===k).value).join('');}
export function titleParts(s){return [s.project,s.scene,s.filename||'DOGMA',s.appendDate?(s.dateMode==='today'?todayCode():s.date||todayCode()):''].map(safeName).filter(Boolean);}
export function prefix(s,f){return ['DOGMA/API',safeName(s.project),safeName(s.scene),titleParts(s).join('_')+'_'+f.short].filter(Boolean).join('/');}
export function migrateState(raw){
 const s=copy(raw);s.schema=4;s.session ||= crypto.randomUUID();s.prompts ||= {image:s.prompt||'',video:''};s.mode ||= 'image';s.imageEdit ??= true;s.appendDate ??= false;s.date ||= todayCode();s.runCount ||= 1;
 s.dateMode ||= raw.schema===1?'manual':'today';if(s.dateMode==='today')s.date=todayCode();
 s.workspace ||= '';s.library ||= [];s.results ||= [];s.references ||= [];s.filters ||= {models:[],project:'*',scene:'*',kind:'all',workspace:'*'};s.density ??= 45;s.workExpanded ??= false;
 for(const m of Object.values(s.models||{})){m.parameters ||= m.variants?.[0]||{};delete m.variants;delete m.editVariant;delete m.seedMode;}
 s.filters.hideErrors ??= false;
 for(const [i,r] of s.references.entries()){r.kind ||= 'image';r.role ||= 'reference';const legacyMask=raw.schema===1&&i===0&&!!raw.maskEnabled;r.process ||= {enabled:legacyMask,mask:legacyMask,maskMode:'edit',invert:false,flip:false,crop:false,resizeMpx:false,megapixels:1,expand:0,blur:0,fillHoles:false,targetWidth:0,targetHeight:0,source:'paint',prompt:'',segment:0,background:'#ff00ff'};}
 if(raw.schema<3)for(const r of [...s.references])if(r.kind==='image'&&r.modes?.includes('video')&&['first','last'].includes(r.role))s.references.push({...copy(r),role:'reference'});
 for(const r of s.results)r.kind ||= 'image';
 return s;
}
export function plannedJobs(s){const repeats=Number(s.runCount??1);if(!Number.isInteger(repeats)||repeats<1||repeats>64)throw new Error('Run deve essere da 1 a 64.');const counts={};return Array.from({length:repeats},(_,repeat)=>families(s).flatMap(f=>{const m=s.models[f.key];if(!m?.enabled)return[];const n=Number(m.quantity);if(!Number.isInteger(n)||n<1||n>64)throw new Error('Quantity deve essere da 1 a 64.');return Array.from({length:n},()=>({family:f.key,index:(counts[f.key]=(counts[f.key]||0)+1)-1,repeat,kind:s.mode==='video'?'video':'image'}));})).flat();}
export const preparedMask=ref=>!!ref.process?.maskFile&&ref.process.samSource===ref.file&&ref.process.samPrompt===ref.process.prompt&&Number(ref.process.samSegment)===Number(ref.process.segment||0);
export function visibleReferences(s){return s.references.filter(r=>(!r.modes||r.modes.includes(s.mode))&&(s.mode==='video'?(s.models.seedance?.engine==='frames'?r.kind==='image'&&['first','last'].includes(r.role):r.role!=='first'&&r.role!=='last'):r.kind!=='video'));}
export function activeReferences(s){return visibleReferences(s).filter(r=>r.enabled);}
export function validateState(s){
 if(!s.prompts[s.mode]?.trim())throw new Error('Scrivi un prompt.');
 if(!plannedJobs(s).length)throw new Error('Attiva almeno un modello.');
 const refs=activeReferences(s),imgs=refs.filter(r=>r.kind==='image'),videos=refs.filter(r=>r.kind==='video');
 if(refs.some(r=>!r.file))throw new Error('Ricarica le reference mancanti.');
 if(s.mode==='image'){
  if(s.imageEdit&&!imgs.length)throw new Error('Image Edit richiede Image 1.');
  const limits={nano:14,gpt:16,flux:10,seedream:10},max=Math.min(...FAMILIES.filter(f=>s.models[f.key]?.enabled).map(f=>limits[f.key]));if(imgs.length>max)throw new Error(`I modelli attivi supportano fino a ${max} reference.`);
 }else {
  const m=s.models.seedance;
  if(m.engine==='frames'&&imgs.length>2)throw new Error('Usa al massimo un First frame e un Last frame.');
  if(m.engine==='frames'&&['first','last'].some(role=>imgs.filter(r=>r.role===role).length>1))throw new Error('Assegna un solo First frame e un solo Last frame.');
  if(m.engine==='frames'&&!imgs.length)throw new Error('Aggiungi almeno un frame immagine.');
  if(m.engine!=='frames'&&!refs.length)throw new Error('Aggiungi una reference immagine o video.');
  const p=m.engine==='frames'?m.frames:m.parameters;
  if(m.engine!=='frames'&&['edit','extend'].includes(p['model.task_type'])&&!videos.length)throw new Error('Video Edit ed Extend richiedono un video sorgente.');
  if(imgs.length>30||videos.length>10)throw new Error('Troppe reference per Seedance 2.5.');
 }
 for(const f of families(s)){
  const m=s.models[f.key];if(!m.enabled)continue;const p=m.engine==='frames'?m.frames:m.parameters;
  for(const [k,v] of Object.entries(p))if(/(?:width|height)$/.test(k)){
   const n=Number(v),min=f.key==='gpt'?480:240,max=f.key==='gpt'?3840:8594,step=f.key==='gpt'?16:2;
   if(!Number.isInteger(n)||n<min||n>max||n%step)throw new Error(`${f.name}: dimensioni da ${min} a ${max}, multiple di ${step}.`);
  }
 }
}
export function compileBatch(s,jobs,baseSeed){
 validateState(s);const output={},refs=activeReferences(s),images=[],videos=[];
 refs.forEach((ref,i)=>{
  const id=String(9000+i*10);output[id]={class_type:ref.kind==='video'?'LoadVideo':'LoadImage',inputs:{[ref.kind==='video'?'file':'image']:ref.file}};
  if(ref.kind==='video'){videos.push({ref,link:[id,0]});return;}
  let link=[id,0];const p=ref.process;
  if(p?.enabled){
   let mask=[id,1];
   if(p.maskFile){const mid=String(9001+i*10);output[mid]={class_type:'LoadImage',inputs:{image:p.maskFile}};const tid=String(9002+i*10);output[tid]={class_type:'ImageToMask',inputs:{image:[mid,0],channel:'red'}};mask=[tid,0];}
   if(p.source==='prompt'&&p.mask&&!preparedMask(ref)){const sid=String(9003+i*10);output[sid]={class_type:'SAM3Segment',inputs:{image:[id,0],prompt:p.prompt,output_mode:'Merged',confidence_threshold:.5,max_segments:0,segment_pick:Number(p.segment||0),mask_blur:0,mask_offset:0,device:'Auto',invert_output:false,unload_model:false,background:'Alpha',background_color:'#222222'}};mask=[sid,1];}
   const pid=String(9004+i*10);output[pid]={class_type:'DOGMAAPIReferenceV2',inputs:{image:[id,0],mask,settings:JSON.stringify(p)}};link=[pid,0];
  }
  images.push({ref,link});
 });
 let nanoBatch=null;
 if(s.mode==='image'&&s.models.nano?.enabled&&images.length){nanoBatch=images[0].link;images.slice(1).forEach((img,i)=>{const id=String(9800+i);output[id]={class_type:'ImageBatch',inputs:{image1:nanoBatch,image2:img.link}};nanoBatch=[id,0];});}
 jobs.forEach((job,i)=>{
  const f=ALL_FAMILIES.find(f=>f.key===job.family),m=s.models[f.key],inputs=copy(m.engine==='frames'?m.frames:m.parameters);
  for(const k of Object.keys(inputs))if(k.startsWith('control_after_generate')||k==='n')delete inputs[k];
  const seed=(Number(baseSeed)+i)%2147483647;inputs[f.key==='seedream'?'model.seed':'seed']=seed;
  const prompt=s.prompts[s.mode];inputs[s.mode==='video'?'model.prompt':'prompt']=prompt;
  let type=f.type;
  if(s.mode==='video'){
   if(m.engine==='frames'){
    type='ByteDance2FirstLastFrameNode';
    const first=images.find(x=>x.ref.role==='first')||images.find(x=>x.ref.role!=='last');const last=images.find(x=>x.ref.role==='last')||images.filter(x=>x!==first)[0];
    if(first)inputs.first_frame=first.link;if(last)inputs.last_frame=last.link;
   }else{images.forEach((x,j)=>inputs[`model.reference_images.image_${j+1}`]=x.link);videos.forEach((x,j)=>inputs[`model.reference_videos.video_${j+1}`]=x.link);}
  }else if(f.key==='nano'){if(nanoBatch)inputs.images=nanoBatch;}
  else{if(f.key==='gpt')inputs.n=1;images.forEach((x,j)=>inputs[`${f.key==='flux'?'':'model.'}images.image_${j+1}`]=x.link);}
  const gen=String(10000+i*10),save=String(10001+i*10);
  Object.assign(job,{seed,generator:gen,output:save,project:s.project||'',scene:s.scene||'',workspace:s.workspace||'',filename:titleParts(s).join('_'),imageEdit:s.mode==='image'&&s.imageEdit,baseReference:s.mode==='image'&&s.imageEdit&&images.length?copy(images[0].ref):null,prompt,parameters:copy(inputs)});
  if(job.baseReference)delete job.baseReference.editorDraft;
  output[gen]={class_type:type,inputs,_meta:{title:`${f.name} ${job.index+1}`}};
  const metadata={...copy(job),session:s.session,prefix:prefix(s,f),date:s.dateMode==='today'?todayCode():s.date,appendDate:s.appendDate};delete metadata.images;delete metadata.parameters;
  output[save]={class_type:s.mode==='video'?'DOGMAAPIVideoOutputV2':'DOGMAAPIImageOutputV2',inputs:{[s.mode==='video'?'video':'images']:[gen,0],metadata:JSON.stringify(metadata)}};
 });
 return {output,jobs};
}
export function orderResults(results){const groups=new Map();for(const r of results){const key=r.batch||r.id;groups.set(key,Math.max(groups.get(key)||0,r.batchStarted||r.started||r.finished||0));}return [...results].sort((a,b)=>{const ga=a.batch||a.id,gb=b.batch||b.id;return groups.get(gb)-groups.get(ga)||(ga===gb?(a.ordinal??a.index??0)-(b.ordinal??b.index??0):String(gb).localeCompare(String(ga)))||String(a.id).localeCompare(String(b.id));});}
export function filterResults(results,filters,now=Date.now()){return results.filter(r=>(!filters.models?.length||filters.models.includes(r.family))&&(filters.project==='*'||(r.project||'')===filters.project)&&(filters.scene==='*'||(r.scene||'')===filters.scene)&&(filters.workspace==='*'||(r.workspace||'')===filters.workspace)&&(filters.kind==='all'||r.kind===filters.kind)&&(!filters.hideErrors||!['failed','missing'].includes(r.status)||(r.errorVisibleUntil||0)>now));}
export function savedFilename(job,index=0){return job.exported?.[index]?.split(/[\\/]/).at(-1)||job.images?.[index]?.filename||job.filename||'';}
