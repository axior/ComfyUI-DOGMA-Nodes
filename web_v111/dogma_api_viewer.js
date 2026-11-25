import { icon } from './dogma_api_icons.js?v=1.0.57';
import {savedFilename} from './dogma_api_core.js?v=1.0.57';

export async function copyFullImage(url){
 if(!navigator.clipboard?.write||!globalThis.ClipboardItem)throw new Error('La copia immagini richiede HTTPS o localhost. Puoi scaricare il file a piena risoluzione.');
 const png=(async()=>{const response=await fetch(url);if(!response.ok)throw new Error('Immagine non disponibile.');const blob=await response.blob();if(blob.type==='image/png')return blob;const bitmap=await createImageBitmap(blob),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;canvas.getContext('2d').drawImage(bitmap,0,0);bitmap.close();return new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Copia immagine non riuscita.')),'image/png'));})();
 await navigator.clipboard.write([new ClipboardItem({'image/png':png})]);
}

function videoComparison(stage,first,second,bridge,dialog,hint){
 stage.classList.add('dap-video-compare');const media=[];
 for(const [i,item] of [first,second].entries()){
  const panel=document.createElement('div');panel.className='dap-video-panel';const label=document.createElement('span');label.textContent=i?'B':'A';const element=document.createElement(item.job.kind==='video'?'video':'img');element.src=bridge.view(item.file);if(element.tagName==='VIDEO'){element.muted=i>0;element.playsInline=true;element.preload='metadata';}panel.append(element,label);stage.append(panel);media.push(element);
 }
 const videos=media.filter(e=>e.tagName==='VIDEO'),controls=document.createElement('div');let master=videos[0];controls.className='dap-video-sync';
 const play=document.createElement('button');play.textContent='Play / Pausa';const seek=document.createElement('input');seek.type='range';seek.min='0';seek.max='0';seek.step='.01';seek.value='0';seek.setAttribute('aria-label','Posizione confronto video');const time=document.createElement('span');
 const pause=()=>videos.forEach(v=>v.pause());
 const sync=()=>{for(const v of videos)if(v!==master&&Number.isFinite(v.duration)&&Math.abs(v.currentTime-master.currentTime)>.12)v.currentTime=Math.min(master.currentTime,v.duration);};
 play.onclick=async()=>{if(!master.paused){pause();return;}if(master.ended)for(const v of videos)v.currentTime=0;sync();try{await Promise.all(videos.filter(v=>!v.ended||v.currentTime===0).map(v=>v.play()));}catch{pause();hint.textContent='Riproduzione non disponibile: controlla i file video.';}};
 seek.oninput=()=>{for(const v of videos)if(Number.isFinite(v.duration))v.currentTime=Math.min(Number(seek.value),v.duration);};
 const update=()=>{const max=Math.max(0,...videos.map(v=>Number.isFinite(v.duration)?v.duration:0));seek.max=String(max);seek.value=String(master.currentTime);time.textContent=`${master.currentTime.toFixed(1)}s / ${max.toFixed(1)}s`;sync();};
 for(const v of videos){v.addEventListener('loadedmetadata',()=>{master=videos.reduce((a,b)=>(b.duration||0)>(a.duration||0)?b:a);update();});v.addEventListener('timeupdate',()=>{if(v===master)update();});v.addEventListener('ended',()=>{if(v===master)pause();});}controls.append(play,seek,time);stage.after(controls);hint.textContent='A / B · Riproduzione e posizione sincronizzate';
 dialog.addEventListener('close',()=>{pause();for(const v of videos){v.removeAttribute('src');v.load();}},{once:true});
}

export function hoverCompare(host,generated,original){
 const a=document.createElement('img');a.src=generated;a.alt='Generata';a.draggable=false;a.className='dap-generated';host.append(a);host.classList.add('dap-compare-host');
 let cover=null,line=null;
 if(original){
  cover=document.createElement('div');cover.className='dap-original-cover';const b=document.createElement('img');b.src=original;b.alt='Image 1 / originale';b.draggable=false;cover.append(b);
  line=document.createElement('div');line.className='dap-compare-line';host.append(cover,line);
  const move=e=>{const rect=host.getBoundingClientRect();const percent=Math.max(0,Math.min(100,(e.clientX-rect.left)/rect.width*100));cover.style.clipPath=`inset(0 ${100-percent}% 0 0)`;line.style.left=percent+'%';};
  host.addEventListener('pointerenter',()=>host.classList.add('comparing'));host.addEventListener('pointermove',move);host.addEventListener('pointerleave',()=>host.classList.remove('comparing'));
 }
 return {image:a,cover,line};
}

export function openViewer(ui,item,other=null){
 const {job,file,index=0}=item,bridge=ui.bridge;
 const title=savedFilename(job,index)||job.label||'DOGMA';
 const dialog=ui.modalBox(title,'dap-viewer-modal',!!item.preview),toolbar=document.createElement('div');toolbar.className='dap-viewer-tools';
 const stage=document.createElement('div');stage.className='dap-viewer-stage';stage.setAttribute('aria-label','Immagine ingrandita: rotella per zoom, trascina per spostare');stage.tabIndex=0;
 const surface=document.createElement('div');surface.className='dap-viewer-surface';stage.append(surface);
 const button=(name,label,fn)=>{const b=document.createElement('button');b.type='button';b.title=label;b.setAttribute('aria-label',label);b.append(icon(name));b.onclick=fn;return b;};
 let scale=1,fitScale=1,x=0,y=0,width=0,height=0,drag=null,pinch=null;const points=new Map();
 const zoom=document.createElement('input');zoom.type='number';zoom.min='1';zoom.max='1600';zoom.setAttribute('aria-label','Zoom percentuale');
 const percent=document.createElement('label');percent.className='dap-zoom-value';percent.append(zoom,document.createTextNode('%'));
 const update=()=>{surface.style.transform=`translate(${x}px,${y}px) scale(${scale})`;zoom.value=String(Math.round(scale*100));stage.classList.toggle('zoomed',scale>fitScale*1.01);};
 const at=(next,cx=stage.clientWidth/2,cy=stage.clientHeight/2)=>{next=Math.max(Math.min(fitScale,.1)*.5,Math.min(16,next));const ratio=next/scale;x=cx-(cx-x)*ratio;y=cy-(cy-y)*ratio;scale=next;update();};
 const fit=()=>{if(!width)return;fitScale=Math.min((stage.clientWidth-30)/width,(stage.clientHeight-30)/height);scale=fitScale;x=(stage.clientWidth-width*scale)/2;y=(stage.clientHeight-height*scale)/2;update();};
 toolbar.append(button('zoomOut','Riduci zoom',()=>at(scale/1.3)),percent,button('zoomIn','Aumenta zoom',()=>at(scale*1.3)),button('fit','Adatta alla finestra',fit));
 const one=button('single','Dimensione reale 100%',()=>at(1));one.append(document.createTextNode('100%'));toolbar.append(one);
 if(job.id){const folder=button('folder','Mostra nella cartella',()=>ui.openOutput(job,index));folder.append(document.createTextNode('Mostra nella cartella'));toolbar.append(folder);}
 const download=button('download','Scarica file',()=>ui.downloadImage(file));toolbar.append(download);
 const hint=document.createElement('p');hint.className='dap-viewer-hint';hint.textContent='Rotella: zoom sul punto · Trascina: sposta · Doppio clic: 100% · Esc o clic nel vuoto: chiudi';
 dialog.append(toolbar,stage,hint);
 if(job.prompt)toolbar.append(button('prompt','Leggi e copia prompt',()=>ui.showPrompt(job)));
 if(job.kind!=='video'){const copy=button('copy','Copia immagine a piena risoluzione',async()=>{try{await copyFullImage(bridge.view(file));hint.textContent='Immagine copiata alla risoluzione originale.';}catch(e){hint.textContent=e.message;}});toolbar.append(copy);}
 if(other&&(job.kind==='video'||other.job.kind==='video')){surface.remove();toolbar.querySelectorAll('button').forEach(b=>{if(b.title.includes('zoom')||b.title.includes('100%')||b.title.includes('Adatta'))b.remove();});percent.remove();videoComparison(stage,item,other,bridge,dialog,hint);return;}
 if(job.kind==='video'){
  const video=document.createElement('video');video.src=bridge.view(file);video.controls=true;video.autoplay=true;video.className='dap-viewer-video';stage.append(video);surface.remove();toolbar.querySelectorAll('button').forEach(b=>{if(b.title.includes('zoom')||b.title.includes('100%')||b.title.includes('Adatta'))b.remove();});percent.remove();hint.textContent='Esc o clic nel vuoto per chiudere';
  dialog.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load();},{once:true});return;
 }
 const original=other?bridge.view(other.file):job.imageEdit&&job.baseReference?(job.baseReference.comparePreview||bridge.view(job.baseReference.processedPreview||job.baseReference.file)):null;
 const compare=hoverCompare(surface,bridge.view(file),original);
 compare.image.onload=()=>{width=compare.image.naturalWidth;height=compare.image.naturalHeight;surface.style.width=width+'px';surface.style.height=height+'px';fit();};
 if(compare.image.complete&&compare.image.naturalWidth)compare.image.onload();
 compare.image.onerror=()=>{hint.textContent='File non disponibile. Potrebbe essere stato spostato.';};
 zoom.onchange=()=>{const value=Number(zoom.value);if(Number.isFinite(value)&&value>0)at(value/100);};
 stage.addEventListener('wheel',e=>{e.preventDefault();const r=stage.getBoundingClientRect();at(scale*Math.exp(-e.deltaY*.0017),e.clientX-r.left,e.clientY-r.top);},{passive:false});
 stage.addEventListener('dblclick',e=>{const r=stage.getBoundingClientRect();if(Math.abs(scale-1)<.02)fit();else at(1,e.clientX-r.left,e.clientY-r.top);});
 stage.addEventListener('pointerdown',e=>{
  const rect=surface.getBoundingClientRect();const inImage=e.clientX>=rect.left&&e.clientX<=rect.right&&e.clientY>=rect.top&&e.clientY<=rect.bottom;
  if(!inImage&&e.target===stage){drag={blank:true,startX:e.clientX,startY:e.clientY};return;}
  stage.setPointerCapture(e.pointerId);points.set(e.pointerId,{x:e.clientX,y:e.clientY});drag={startX:e.clientX,startY:e.clientY,x,y};
  if(points.size===2){const [a,b]=[...points.values()];pinch={distance:Math.hypot(a.x-b.x,a.y-b.y),scale};}
 });
 stage.addEventListener('pointermove',e=>{
  if(points.has(e.pointerId))points.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(points.size===2&&pinch){const [a,b]=[...points.values()],r=stage.getBoundingClientRect();at(pinch.scale*Math.hypot(a.x-b.x,a.y-b.y)/pinch.distance,(a.x+b.x)/2-r.left,(a.y+b.y)/2-r.top);return;}
  if(drag&&!drag.blank&&points.size===1){x=drag.x+e.clientX-drag.startX;y=drag.y+e.clientY-drag.startY;update();}
 });
 const up=e=>{if(drag?.blank&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5)dialog.close();points.delete(e.pointerId);drag=null;pinch=null;};
 stage.addEventListener('pointerup',up);stage.addEventListener('pointercancel',up);
 stage.addEventListener('keydown',e=>{if(e.key==='+'||e.key==='='){e.preventDefault();at(scale*1.3);}if(e.key==='-'){e.preventDefault();at(scale/1.3);}if(e.key==='0'){e.preventDefault();fit();}});
 const observer=new ResizeObserver(()=>{if(Math.abs(scale-fitScale)<.01)fit();});observer.observe(stage);dialog.addEventListener('close',()=>observer.disconnect(),{once:true});
}
