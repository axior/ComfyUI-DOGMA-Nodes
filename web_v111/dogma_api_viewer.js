import { icon } from './dogma_api_icons.js?v=1.0.54';

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
 const title=job.filename||job.label||'DOGMA';
 const dialog=ui.modalBox(title,'dap-viewer-modal'),toolbar=document.createElement('div');toolbar.className='dap-viewer-tools';
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
 const folder=button('folder','Mostra nella cartella',()=>ui.openOutput(job,index));folder.append(document.createTextNode('Mostra nella cartella'));toolbar.append(folder);
 const download=button('download','Scarica file',()=>ui.downloadImage(file));toolbar.append(download);
 const hint=document.createElement('p');hint.className='dap-viewer-hint';hint.textContent='Rotella: zoom sul punto · Trascina: sposta · Doppio clic: 100% · Esc o clic nel vuoto: chiudi';
 dialog.append(toolbar,stage,hint);
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
