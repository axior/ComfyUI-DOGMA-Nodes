import {copy} from './dogma_api_core.js?v=1.0.54';
import {icon} from './dogma_api_icons.js?v=1.0.54';

export async function referenceEditor(ui,ref){
 const make=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
 const button=(text,fn,cls='dap-outline')=>{const b=make('button',text,cls);b.type='button';b.onclick=fn;return b;};
 const box=ui.modalBox('REFERENCE / CROP / MASK','dap-reference-modal'),layout=make('div','','dap-reference-layout'),left=make('div','','dap-reference-left'),right=make('div','','dap-reference-options');
 const tools=make('div','','dap-reference-tools'),stage=make('div','','dap-mask-stage'),base=make('canvas'),overlay=make('canvas');stage.append(base,overlay);left.append(tools,stage);
 const draft={enabled:true,mask:false,source:'paint',maskMode:'isolate',flip:false,invert:false,crop:false,resizeMpx:false,megapixels:1,expand:0,blur:0,fillHoles:true,targetWidth:0,targetHeight:0,segment:0,prompt:'',background:'#00ff00',...copy(ref.process||{})};
 layout.append(left,right);box.append(layout);
 const status=make('div','','dap-editor-status');left.append(status);
 let tool='brush',brush=40,down=null,maskChanged=false,previewFile=ref.processedPreview||null;const undo=[],fields=new Map();
 const mask=make('canvas'),mc=mask.getContext('2d',{willReadFrequently:true}),oc=overlay.getContext('2d',{willReadFrequently:true}),bc=base.getContext('2d',{willReadFrequently:true});
 const image=new Image();image.crossOrigin='anonymous';image.src=ref.preview||ui.bridge.view(ref.file);
 try{await image.decode();if(!box.isConnected)return;}catch{status.textContent='Reference assente. Sostituiscila per modificarla.';left.append(button('Sostituisci reference',()=>{box.close();ui.pickReferences(ref);}));return;}
 base.width=overlay.width=mask.width=image.naturalWidth;base.height=overlay.height=mask.height=image.naturalHeight;
 stage.style.width=`min(100%, ${55*image.naturalWidth/image.naturalHeight}vh)`;
 bc.drawImage(image,0,0);const source=bc.getImageData(0,0,base.width,base.height),initial=mc.createImageData(mask.width,mask.height);
 for(let i=0;i<source.data.length;i+=4){const value=255-source.data[i+3];initial.data[i]=initial.data[i+1]=initial.data[i+2]=255;initial.data[i+3]=value;source.data[i+3]=255;}bc.putImageData(source,0,0);mc.putImageData(initial,0,0);
 if(draft.maskFile){try{const saved=new Image();saved.crossOrigin='anonymous';saved.src=ui.bridge.view(draft.maskFile);await saved.decode();const temp=make('canvas');temp.width=mask.width;temp.height=mask.height;const ctx=temp.getContext('2d');ctx.drawImage(saved,0,0,mask.width,mask.height);const pixels=ctx.getImageData(0,0,mask.width,mask.height);for(let i=0;i<pixels.data.length;i+=4){pixels.data[i+3]=pixels.data[i];pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=255;}mc.putImageData(pixels,0,0);}catch{status.textContent='Maschera salvata non disponibile.';}}
 const draw=()=>{
  const pixels=mc.getImageData(0,0,mask.width,mask.height);for(let i=0;i<pixels.data.length;i+=4){pixels.data[i]=255;pixels.data[i+1]=100;pixels.data[i+2]=37;pixels.data[i+3]=Math.round((draft.invert?255-pixels.data[i+3]:pixels.data[i+3])*.5);}oc.putImageData(pixels,0,0);
  if(draft.cropRect&&draft.crop){const [x,y,w,h]=draft.cropRect;oc.strokeStyle='#fff';oc.lineWidth=Math.max(1,mask.width/700);oc.setLineDash([mask.width/100,mask.width/150]);oc.strokeRect(x*mask.width,y*mask.height,w*mask.width,h*mask.height);oc.setLineDash([]);}
 };
 const mark=()=>{previewFile=null;status.textContent='Impostazioni modificate · Anteprima per controllare il risultato.';draw();};
 const saveUndo=()=>{undo.push({pixels:mc.getImageData(0,0,mask.width,mask.height),rect:draft.cropRect?copy(draft.cropRect):null});if(undo.length>10)undo.shift();};
 const setTool=value=>{tool=value;for(const b of tools.querySelectorAll('[data-tool]'))b.classList.toggle('active',b.dataset.tool===value);overlay.style.cursor=value==='brush'||value==='erase'?'crosshair':'cell';};
 for(const [key,title] of [['brush','Pennello'],['erase','Gomma'],['crop','Crop rettangolare']]){const b=button(title,()=>setTool(key),'dap-editor-tool');b.dataset.tool=key;tools.append(b);}
 const size=make('input');size.type='range';size.min='2';size.max='180';size.value='40';size.setAttribute('aria-label','Dimensione pennello');size.oninput=()=>brush=Number(size.value);tools.append(size);
 tools.append(button('Undo',()=>{const previous=undo.pop();if(!previous)return;mc.putImageData(previous.pixels,0,0);draft.cropRect=previous.rect;maskChanged=true;mark();}),button('Pulisci',()=>{saveUndo();mc.clearRect(0,0,mask.width,mask.height);delete draft.cropRect;maskChanged=true;mark();}));
 const point=e=>{const r=overlay.getBoundingClientRect();return [Math.max(0,Math.min(mask.width,(e.clientX-r.left)*mask.width/r.width)),Math.max(0,Math.min(mask.height,(e.clientY-r.top)*mask.height/r.height))];};
 const stroke=(from,to)=>{mc.globalCompositeOperation=tool==='erase'?'destination-out':'source-over';mc.lineWidth=brush*mask.width/1000;mc.strokeStyle='#fff';mc.lineCap='round';mc.beginPath();mc.moveTo(...from);mc.lineTo(...to);mc.stroke();mc.globalCompositeOperation='source-over';maskChanged=true;draft.mask=true;draft.source='paint';if(fields.has('mask'))fields.get('mask').checked=true;if(fields.has('source'))fields.get('source').value='paint';};
 overlay.onpointerdown=e=>{saveUndo();down={first:point(e),last:point(e)};overlay.setPointerCapture(e.pointerId);if(tool!=='crop')stroke(down.first,[down.first[0]+.01,down.first[1]]);draw();};
 overlay.onpointermove=e=>{if(!down)return;const p=point(e);if(tool==='crop'){draft.crop=true;if(fields.has('crop'))fields.get('crop').checked=true;const x=Math.min(p[0],down.first[0]),y=Math.min(p[1],down.first[1]);draft.cropRect=[x/mask.width,y/mask.height,Math.abs(p[0]-down.first[0])/mask.width,Math.abs(p[1]-down.first[1])/mask.height];}else stroke(down.last,p);down.last=p;draw();};
 overlay.onpointerup=overlay.onpointercancel=()=>{if(down){down=null;mark();}};
 const field=(name,key,opts={})=>{const input=ui.field(right,name,draft[key],v=>{draft[key]=typeof draft[key]==='number'?Number(v):v;mark();},opts);fields.set(key,input);return input;};
 right.append(make('div','PREPARAZIONE REFERENCE','dap-label'));
 field('MASK', 'mask',{type:'checkbox'});field('MASK MODE','maskMode',{choices:['isolate','edit']});field('MASK SOURCE','source',{choices:['paint','prompt']});
 field('MASK PROMPT','prompt');field('SEGMENT','segment',{type:'number',min:0,max:100});field('INVERT MASK','invert',{type:'checkbox'});field('HORIZONTAL FLIP','flip',{type:'checkbox'});field('CROP','crop',{type:'checkbox'});
 field('EXPAND / PX','expand',{type:'number',min:-512,max:512});field('BLUR / PX','blur',{type:'number',min:0,max:128,step:.1});field('FILL HOLES','fillHoles',{type:'checkbox'});
 field('RESIZE TO MPX','resizeMpx',{type:'checkbox'});field('MEGAPIXELS','megapixels',{type:'number',min:.01,max:64,step:.1});field('CROP WIDTH','targetWidth',{type:'number',min:0,max:16384});field('CROP HEIGHT','targetHeight',{type:'number',min:0,max:16384});field('BACKGROUND','background',{type:'color'});
 right.append(make('p','Isolate mantiene l’area dipinta e colora il resto. Edit colora l’area dipinta. Crop usa il rettangolo o i bordi della maschera; dimensioni 0 mantengono il crop originale. Prompt usa il nodo SAM3 del workflow.','dap-field-hint'));
 const preview=make('img','','dap-reference-preview');preview.alt='Anteprima della reference preparata';preview.hidden=!previewFile;if(previewFile)preview.src=ui.bridge.view(previewFile);right.append(preview);
 async function uploadMask(){if(!maskChanged)return;const out=make('canvas');out.width=mask.width;out.height=mask.height;const ctx=out.getContext('2d'),pixels=mc.getImageData(0,0,mask.width,mask.height);for(let i=0;i<pixels.data.length;i+=4){const v=pixels.data[i+3];pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=v;pixels.data[i+3]=255;}ctx.putImageData(pixels,0,0);const blob=await new Promise(resolve=>out.toBlob(resolve,'image/png'));if(!blob)throw new Error('Maschera non esportata.');const result=await ui.bridge.upload(new File([blob],'DOGMA_mask_'+Date.now()+'.png',{type:'image/png'}));draft.maskFile=result.file;maskChanged=false;}
 const footer=make('div','','dap-reference-footer');
 const previewButton=button('Anteprima',async()=>{previewButton.disabled=true;try{await uploadMask();const result=await ui.bridge.previewReference(ref,draft);if(!box.isConnected)return;previewFile=result.file;preview.src=ui.bridge.view(previewFile);preview.hidden=false;status.textContent=`${result.width} × ${result.height} · Anteprima aggiornata`;}catch(e){status.textContent=e.message;}finally{previewButton.disabled=false;}});
 footer.append(button('Sostituisci file',()=>{box.close();ui.pickReferences(ref);}),previewButton,button('Applica',async()=>{try{await uploadMask();ref.process=copy(draft);ref.process.enabled=true;ref.processedPreview=previewFile;ui.save();ui.renderRefs();ui.refreshPrices();box.close();ui.note('Preparazione reference salvata.');}catch(e){status.textContent=e.message;}},'dap-primary'));
 box.append(footer);setTool('brush');draw();
}
