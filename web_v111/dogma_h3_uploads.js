import {mediaPreview,inputFile} from './dogma_h3_media.js?v=studio-1-0-49';
import {actionButton,setAction} from './dogma_h3_actions.js?v=studio-1-0-49';
const el=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
const extensions={image:new Set(['png','jpg','jpeg','webp','gif','bmp','tif','tiff','avif','heic','heif']),video:new Set(['mp4','mov','m4v','mkv','webm','avi','mpeg','mpg','wmv','flv','ts','mts','m2ts','mxf','ogv','3gp'])};
export function mediaKind(file){const mime=String(file.type||'').toLowerCase();if(mime.startsWith('image/'))return 'image';if(mime.startsWith('video/'))return 'video';const ext=String(file.name||'').split('.').pop().toLowerCase();return Object.keys(extensions).find(kind=>extensions[kind].has(ext));}
export function validateFiles(files,kind,{multiple=false}={}){
 if(!files.length)throw Error('Nessun file da caricare.');
 if(!multiple&&files.length!==1)throw Error('Questa area accetta un solo file alla volta.');
 for(const f of files){const actual=mediaKind(f);if(!actual||kind!=='media'&&actual!==kind)throw Error(`«${f.name}»: qui puoi caricare ${kind==='image'?'un’immagine':kind==='video'?'un video':'immagini e video'}.`);if(!f.size)throw Error(`«${f.name}» è vuoto e non può essere caricato.`);}
 return files;
}
export function referencePlan(refs,files,limits){
 validateFiles(files,'media',{multiple:true});
 for(const kind of ['image','video']){const present=refs.filter(r=>r.kind===kind&&r.name).length,incoming=files.filter(f=>mediaKind(f)===kind).length;if(present+incoming>limits[kind])throw Error(`Limite reference: massimo ${limits.image} immagini e ${limits.video} video aggiuntivi. Riduci i file selezionati.`);}
 return files.map(file=>({file,kind:mediaKind(file)}));
}
const fileTransfer=e=>Array.from(e.dataTransfer?.types||[]).includes('Files')||!!e.dataTransfer?.files?.length;
export function dropTarget(root,kind,submit,notice,{multiple=false,label=''}={}){
 root.classList.add('dg-file-drop');root.dataset.fileKind=kind;if(label)root.setAttribute('aria-label',label);
 let depth=0;const reset=()=>{depth=0;delete root.dataset.dragging;};
 root.addEventListener('dragenter',e=>{if(!fileTransfer(e))return;e.preventDefault();e.stopPropagation();depth++;root.dataset.dragging='true';});
 root.addEventListener('dragover',e=>{if(!fileTransfer(e))return;e.preventDefault();e.stopPropagation();e.dataTransfer.dropEffect='copy';root.dataset.dragging='true';});
 root.addEventListener('dragleave',e=>{if(!depth)return;e.stopPropagation();depth=Math.max(0,depth-1);if(!depth)delete root.dataset.dragging;});
 root.addEventListener('drop',e=>{
  if(!fileTransfer(e))return;e.preventDefault();e.stopPropagation();reset();
  try{
   if(Array.from(e.dataTransfer.items||[]).some(item=>item.webkitGetAsEntry?.()?.isDirectory))throw Error('Trascina i singoli file, senza cartelle.');
   const files=Array.from(e.dataTransfer.files||[]);validateFiles(files,kind,{multiple});submit(files);
  }catch(error){notice(error.message,true);}
 });
 return reset;
}
export function guardFileNavigation(dialog){
 dialog.addEventListener('dragover',e=>{if(fileTransfer(e)){e.preventDefault();e.dataTransfer.dropEffect='none';}});
 dialog.addEventListener('drop',e=>{if(!fileTransfer(e))return;e.preventDefault();const toast=el('div','Rilascia il file in un’area di caricamento.','dg-upload-toast');toast.setAttribute('role','status');dialog.append(toast);setTimeout(()=>toast.remove(),3500);});
}
function current(studio,config,session,epoch){return studio.config===config&&studio.config.session===session&&studio.epoch===epoch;}
async function upload(studio,file){const data=new FormData();data.append('image',file);data.append('type','input');data.append('subfolder','DOGMA_DIRECTOR');const response=await studio.request('/upload/image',{method:'POST',body:data});return (response.subfolder?response.subfolder+'/':'')+response.name;}
function hint(root,text){const h=el('div','','dg-drop-hint');setAction(h,text,'upload');root.append(h);return h;}
export function assetField(studio,parent,title,obj,key,kind='image',options={}){
 const root=studio.section(parent,title),name=obj[key];let busy=false;
 if(name&&options.preview!==false)root.append(mediaPreview(inputFile(name),{kind,className:'dg-asset'}).root);
 if(name)root.append(el('small',name));
 hint(root,kind==='video'?'Trascina qui un video':'Trascina qui un’immagine');
 const picker=el('input');picker.type='file';picker.accept=kind==='video'?'video/*':'image/*';picker.hidden=true;
 const notice=el('p','','dg-upload-status');notice.setAttribute('role','status');
 const message=(text,error=false)=>{notice.textContent=text;root.dataset.uploadState=error?'error':busy?'uploading':'idle';};
 const choose=actionButton(name?(options.changeLabel||'Cambia file'):(options.loadLabel||'Carica file'),()=>{if(studio.uploads>0)message('Attendi il caricamento già in corso.');else picker.click();});let remove;
 if(options.allowRemove!==false&&(name||options.remove))remove=actionButton('Rimuovi',()=>{if(options.remove)options.remove();else obj[key]='';studio.save();studio.render();});
 const send=async files=>{
  if(busy||studio.uploads>0){message('Attendi il caricamento già in corso.');return;}
  try{validateFiles(files,kind);}catch(error){message(error.message,true);return;}
  busy=true;choose.disabled=true;if(remove)remove.disabled=true;root.setAttribute('aria-busy','true');studio.uploads=(studio.uploads||0)+1;studio.status();message('Caricamento di '+files[0].name+'…');
  const config=studio.config,session=config.session,epoch=studio.epoch;
  try{
   const name=await upload(studio,files[0]);if(!current(studio,config,session,epoch))return;
   obj[key]=name;options.onUploaded?.(name);studio.save();studio.render();
  }catch(error){if(error.name!=='AbortError')message(error.message,true);}
  finally{busy=false;root.setAttribute('aria-busy','false');choose.disabled=false;if(remove)remove.disabled=false;studio.uploads=Math.max(0,(studio.uploads||1)-1);studio.status();}
 };
 picker.onchange=()=>{const files=Array.from(picker.files||[]);picker.value='';if(files.length)send(files);};
 root.append(picker,choose);if(remove)root.append(remove);root.append(notice);
 dropTarget(root,kind,send,message,{label:title});return root;
}
export function referenceDrop(studio,root,{image=9,video=3}={}){
 const limits={image,video};let busy=false;
 hint(root,'Trascina qui immagini e video di riferimento, anche più file insieme');
 const notice=el('p',studio.referenceUploadNotice||'','dg-upload-status');notice.setAttribute('role','status');root.append(notice);
 const message=(text,error=false)=>{notice.textContent=text;root.dataset.uploadState=error?'error':busy?'uploading':'idle';};
 const send=async files=>{
  if(busy||studio.uploads>0){message('Attendi il caricamento già in corso.');return;}
  let plan;try{plan=referencePlan(studio.config.refs,files,limits);}catch(error){message(error.message,true);return;}
  busy=true;studio.uploads=(studio.uploads||0)+1;studio.status();root.setAttribute('aria-busy','true');
  const config=studio.config,session=config.session,epoch=studio.epoch;let done=0;const errors=[];
  try{
   for(const [i,entry]of plan.entries()){
    message(`Caricamento reference ${i+1}/${plan.length}: ${entry.file.name}…`);
    try{
     const name=await upload(studio,entry.file);if(!current(studio,config,session,epoch))throw new DOMException('Caricamento annullato','AbortError');
     const empty=config.refs.find(r=>r.kind===entry.kind&&!r.name);
     if(empty)empty.name=name;else config.refs.push({kind:entry.kind,name});done++;studio.save();
    }catch(error){if(error.name==='AbortError')throw error;errors.push(entry.file.name+': '+error.message);}
   }
   studio.referenceUploadNotice=errors.length?`Caricati ${done} file. `+errors.join(' · '):`Caricati ${done} file di riferimento.`;
   if(done)studio.render();else message(studio.referenceUploadNotice,true);
  }catch(error){if(error.name!=='AbortError')message(error.message,true);}
  finally{busy=false;root.setAttribute('aria-busy','false');studio.uploads=Math.max(0,(studio.uploads||1)-1);studio.status();}
 };
 dropTarget(root,'media',send,message,{multiple:true,label:'Reference: trascina immagini e video'});
 const pickers={};for(const kind of ['image','video']){const picker=el('input');picker.type='file';picker.accept=kind+'/*';picker.multiple=true;picker.hidden=true;picker.onchange=()=>{const files=Array.from(picker.files||[]);picker.value='';if(files.length)send(files);};pickers[kind]=picker;root.append(picker);}
 return {choose:kind=>{if(!busy&&!studio.uploads)pickers[kind].click();else message('Attendi il caricamento già in corso.');}};
}
