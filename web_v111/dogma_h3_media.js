import { api } from '../../scripts/api.js';

const el=(tag,text='')=>{const e=document.createElement(tag);e.textContent=text;return e;};
export function inputFile(name){
 const path=name.replaceAll('\\','/'),i=path.lastIndexOf('/');
 return {filename:path.slice(i+1),subfolder:i<0?'':path.slice(0,i),type:'input'};
}
export const viewURL=file=>api.apiURL('/view?'+new URLSearchParams(file));

export function mediaPreview(file,{kind='video',className='',loop=false}={}){
 const root=el('div');root.className='dg-media-preview';
 const media=el(kind==='image'?'img':'video');media.className=className;
 if(kind==='image')media.alt=file.filename;else{media.controls=true;media.playsInline=true;media.preload='auto';media.loop=loop;}
 const status=el('div');status.className='dg-media-status';status.setAttribute('role','status');
 const label=el('span'),retry=el('button','Ricarica anteprima');retry.type='button';retry.hidden=true;
 status.append(label,retry);root.append(media,status);
 const abort=new AbortController();let closed=false,timer,attempt=0,resume=0;
 const message=(text,error=false)=>{if(closed)return;root.dataset.state=error?'error':'loading';label.textContent=text;status.hidden=false;retry.hidden=!error;};
 const ready=()=>{if(closed)return;clearTimeout(timer);root.dataset.state='ready';status.hidden=true;};
 const load=()=>{
  clearTimeout(timer);resume=kind==='video'?media.currentTime||0:0;
  message('Caricamento anteprima…');
  media.src=viewURL({...file,...(attempt?{dg_reload:attempt}: {})});
  if(kind!=='image')media.load();
  timer=setTimeout(()=>message('Anteprima in attesa. Puoi ricaricarla senza perdere la selezione.',true),15000);
 };
 retry.onclick=()=>{attempt++;load();};
 media.addEventListener(kind==='image'?'load':'loadeddata',ready,{signal:abort.signal});
 media.addEventListener('loadedmetadata',()=>{if(resume>0)media.currentTime=Math.min(resume,media.duration);},{signal:abort.signal});
 media.addEventListener('error',async()=>{
  clearTimeout(timer);const current=attempt;
  message('Impossibile aprire l’anteprima. Verifico il file…',true);
  try{
   const response=await api.fetchApi('/view?'+new URLSearchParams(file),{method:'HEAD',signal:abort.signal});
   if(closed||current!==attempt)return;
   if(response.status===404)message('File non trovato. Ricarica il file sorgente.',true);
   else if(!response.ok)message(`Anteprima non disponibile (errore ${response.status}). Riprova.`,true);
   else message(kind==='image'?'Immagine non leggibile dal browser. Prova PNG o JPEG.':'Il file esiste, ma il browser non riesce a decodificarlo. Per l’anteprima usa MP4 H.264.',true);
  }catch(e){if(!closed&&current===attempt&&e.name!=='AbortError')message('Connessione interrotta. Ricarica l’anteprima.',true);}
 },{signal:abort.signal});
 const destroy=()=>{if(closed)return;closed=true;clearTimeout(timer);abort.abort();retry.onclick=null;if(kind!=='image')media.pause();media.removeAttribute('src');if(kind!=='image')media.load();};
 root._dogmaMedia={destroy};load();
 return {root,media,destroy,reload:()=>{attempt++;load();}};
}

export function releaseMedia(root){
 for(const e of root?.querySelectorAll('.dg-media-preview')||[])e._dogmaMedia.destroy();
}
