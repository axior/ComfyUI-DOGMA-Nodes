import {viewURL} from './dogma_h3_media.js?v=studio-1-0-48';
import {actionButton,setAction} from './dogma_h3_actions.js?v=studio-1-0-48';
const el=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
const clamp=(x,a,b)=>Math.min(b,Math.max(a,x));
export class RestitchPanel{
 constructor(studio,parent,item){
  this.studio=studio;this.item=item;this.closed=false;this.abort=new AbortController();
  this.root=el('details','','dg-card dg-restitch');this.root.append(el('summary','Rifinisci maschera · preset e impostazioni personali'));parent.append(this.root);
  this.body=el('div');this.root.append(this.body);this.notice=el('p');this.notice.setAttribute('role','status');this.body.append(this.notice);
  this.root.addEventListener('toggle',()=>{if(this.closed)return;if(this.root.open){studio.restitchOpenFor=item.id;this.start();}else{studio.restitchOpenFor=null;this.release();this.started=false;}},{signal:this.abort.signal});
  if(studio.restitchOpenFor===item.id)this.root.open=true;
 }
 async job(path,data){
  const request=await this.studio.request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:this.abort.signal});
  for(;;){
   const result=await this.studio.request('/dogma/h3/v2/edit/restitch/job/'+request.id,{signal:this.abort.signal});
   if(result.status==='done')return result.result;if(result.status==='error')throw Error(result.message);
   await new Promise(resolve=>{this.pollTimer=setTimeout(resolve,250);this.pollResolve=resolve;});
   if(this.closed||!this.root.open)throw new DOMException('Pannello chiuso','AbortError');
  }
 }
 async start(){
  if(this.started||this.closed)return;this.started=true;delete this.root.dataset.readyMs;this.openedAt=performance.now();this.body.replaceChildren(this.notice);this.notice.textContent='Preparazione delle anteprime condivise…';
  const epoch=this.loadEpoch=(this.loadEpoch||0)+1;
  try{
   const info=await this.job('/dogma/h3/v2/edit/restitch/preview',{session:this.studio.config.session,id:this.item.id});
   if(this.closed||!this.root.open||epoch!==this.loadEpoch)return;
   this.info=info;this.build();
  }catch(e){if(this.closed||e.name==='AbortError')return;this.notice.textContent=e.message;this.body.append(actionButton('Riprova',()=>{this.started=false;this.start();}));}
 }
 build(){
  const info=this.info,scale=Math.max(.25,info.source_width/1664),r=n=>Math.round(n*scale),g=info.base.grow,f=info.base.feather;
  this.presets=[{id:'current',label:'Attuale',grow:g,feather:f},{id:'soft',label:'Raccordo morbido',grow:g,feather:f+r(8)},
   {id:'expand',label:'Espansione lieve',grow:g+r(4),feather:Math.max(f,r(8))},{id:'expand-soft',label:'Espansione progressiva',grow:g+r(12),feather:f+r(16)},
   {id:'contract',label:'Contrazione lieve',grow:g-r(4),feather:Math.max(f,r(8))},{id:'contract-soft',label:'Contrazione progressiva',grow:g-r(12),feather:f+r(8)}];
  for(const p of this.presets){p.grow=clamp(p.grow,-256,256);p.feather=clamp(p.feather,0,256);}
  this.studio.restitchDrafts??={};const draft=this.studio.restitchDrafts[this.item.id];
  this.custom={id:'custom',label:'Personalizzata',grow:draft?.grow??g,feather:draft?.feather??f};this.presets.push(this.custom);this.selected=this.presets.find(p=>p.id===draft?.selected)||this.presets[0];
  this.body.replaceChildren();this.body.append(el('p','Tutte le anteprime sono sincronizzate e in loop. Le prove non modificano il file salvato; applica soltanto quella scelta.'));
  this.toolbar=el('div','','dg-edit-controls');this.playButton=actionButton('Pausa anteprime',()=>{if(this.video.paused)this.play();else this.video.pause();});
  this.scrub=el('input');this.scrub.type='range';this.scrub.min=0;this.scrub.max=info.duration;this.scrub.step=1/info.fps;this.scrub.setAttribute('aria-label','Posizione di tutte le anteprime restitch');
  this.scrub.oninput=()=>{this.video.currentTime=Number(this.scrub.value);};this.position=el('span','0.00 s');this.toolbar.append(this.playButton,this.position);this.body.append(this.toolbar,this.scrub);
  const grid=el('div','','dg-restitch-grid');this.cards=[];this.canvases=[];
  for(const p of this.presets){
   const card=actionButton('',()=>this.choose(p));card.className='dg-restitch-choice';card.setAttribute('aria-label','Seleziona '+p.label);card.setAttribute('aria-pressed',String(p===this.selected));
   const title=el('strong',p.label),canvas=el('canvas'),settings=el('small');canvas.width=info.width;canvas.height=info.height;canvas.setAttribute('aria-label','Anteprima '+p.label);this.canvases.push(canvas);this.cards.push({card,title,settings,p});card.replaceChildren(title,canvas,settings);grid.append(card);
  }
  this.body.append(grid);
  const manual=el('div','','dg-grid');
  for(const [key,label,min,max]of[['grow','Espansione / contrazione · px',-256,256],['feather','Feather interno · px',0,256]]){
   const wrap=el('label','','dg-field'),input=el('input');wrap.append(el('span',label));input.type='number';input.min=min;input.max=max;input.step=1;input.value=this.custom[key];
   input.oninput=()=>{if(!Number.isFinite(input.valueAsNumber))return;this.custom[key]=clamp(input.valueAsNumber,min,max);this.choose(this.custom);if(this.video.paused)this.draw();};input.onchange=()=>{input.value=this.custom[key];};wrap.append(input);manual.append(wrap);
  }
  this.body.append(el('h3','Impostazioni personali'),manual);
  this.applyButton=actionButton('Applica al finale',()=>this.apply(),'dg-primary');this.body.append(this.applyButton);
  this.body.append(el('small',`Anteprime ${info.width} × ${info.height} px · il salvataggio usa i pixel e i tempi del sorgente. Una sola anteprima temporanea condivisa; nessun file per ogni preset. La sfumatura in anteprima è indicativa alla risoluzione ridotta.`));
  this.body.append(this.notice);this.notice.textContent='';this.refresh();
  this.video=el('video');this.video.muted=true;this.video.loop=true;this.video.playsInline=true;this.video.preload='auto';this.video.className='dg-restitch-source';this.video.setAttribute('aria-hidden','true');this.body.append(this.video);
  this.video.addEventListener('loadeddata',()=>{if(this.closed||!this.root.open)return;try{this.renderer=new Renderer(this.info,this.canvases);this.play();}catch(e){this.notice.textContent=e.message;}},{signal:this.abort.signal});
  this.video.addEventListener('error',()=>{this.notice.textContent='Anteprima condivisa non leggibile. Chiudi e riapri la sezione per riprovare.';},{signal:this.abort.signal});
  this.video.addEventListener('seeked',()=>this.draw(),{signal:this.abort.signal});
  this.video.addEventListener('play',()=>{setAction(this.playButton,'Pausa anteprime');this.schedule();},{signal:this.abort.signal});
  this.video.addEventListener('pause',()=>{this.cancelFrame();setAction(this.playButton,'Riproduci anteprime');},{signal:this.abort.signal});
  this.video.src=viewURL(info.file);this.video.load();
 }
 choose(p){this.selected=p;this.studio.restitchDrafts[this.item.id]={grow:this.custom.grow,feather:this.custom.feather,selected:p.id};this.refresh();if(this.video?.paused)this.draw();}
 refresh(){
  for(const c of this.cards){c.card.setAttribute('aria-pressed',String(c.p===this.selected));c.settings.textContent=`${c.p.grow>0?'+':''}${c.p.grow} px · feather ${c.p.feather} px`;}
  if(this.applyButton)this.applyButton.disabled=this.applying||this.studio.pending||this.selected.grow===this.info.base.grow&&this.selected.feather===this.info.base.feather;
 }
 play(){if(!this.renderer)return;this.studio.editCompare?.pause();this.video.play().catch(()=>{setAction(this.playButton,'Riproduci anteprime');this.notice.textContent='Premi Riproduci anteprime per avviare tutti i riquadri.';});}
 schedule(){this.cancelFrame();if(this.closed||!this.video||this.video.paused)return;const next=()=>{if(this.closed||this.video?.paused)return;this.draw();this.schedule();};if(this.video.requestVideoFrameCallback)this.frame=this.video.requestVideoFrameCallback(next);else this.raf=requestAnimationFrame(next);}
 cancelFrame(){if(this.frame!=null)this.video?.cancelVideoFrameCallback?.(this.frame);cancelAnimationFrame(this.raf);this.frame=null;}
 draw(){if(!this.renderer||!this.video||this.video.readyState<2)return;this.renderer.draw(this.video,this.presets);if(!this.root.dataset.readyMs)this.root.dataset.readyMs=Math.round(performance.now()-this.openedAt);this.scrub.value=this.video.currentTime;this.position.textContent=this.video.currentTime.toFixed(2)+' s';for(const c of this.canvases)c.dataset.time=this.video.currentTime.toFixed(6);}
 async apply(){
  if(this.applyButton.disabled)return;this.applying=true;this.refresh();this.notice.textContent='Applicazione alla dimensione originale… Nessuna nuova generazione.';
  try{
   const result=await this.job('/dogma/h3/v2/edit/restitch/apply',{session:this.studio.config.session,id:this.item.id,revision:this.info.revision,grow:this.selected.grow,feather:this.selected.feather});
   if(this.closed)return;Object.assign(this.item,result);this.studio.restitchDrafts[this.item.id]={grow:this.selected.grow,feather:this.selected.feather,selected:'current'};this.studio.data.message=result.export_error||'Restitch applicato al finale.';this.applying=false;this.studio.render();
  }catch(e){if(this.closed||e.name==='AbortError')return;this.applying=false;this.notice.textContent=e.message;this.refresh();}
 }
 release(){this.applying=false;this.loadEpoch=(this.loadEpoch||0)+1;this.cancelFrame();this.video?.pause();if(this.video){this.video.removeAttribute('src');this.video.load();}this.video=null;this.renderer?.destroy();this.renderer=null;clearTimeout(this.pollTimer);this.pollResolve?.();}
 destroy(){if(this.closed)return;this.closed=true;this.release();this.abort.abort();}
}

class Renderer{
 constructor(info,canvases){
  this.info=info;this.canvases=canvases;this.contexts=canvases.map(c=>c.getContext('2d'));this.output=document.createElement('canvas');this.output.width=info.width*canvases.length;this.output.height=info.height;
  const gl=this.gl=this.output.getContext('webgl',{alpha:false,antialias:false,preserveDrawingBuffer:true});
  if(!gl){this.cpu=document.createElement('canvas');this.cpu.width=info.width*4;this.cpu.height=info.height;this.cpuContext=this.cpu.getContext('2d',{willReadFrequently:true});return;}
  const vertex='attribute vec2 p;varying vec2 uv;void main(){uv=p*.5+.5;gl_Position=vec4(p,0.,1.);}';
  const fragment=`precision highp float;varying vec2 uv;uniform sampler2D atlas;uniform vec2 size;uniform vec2 source;uniform float grow;uniform float feather;uniform float range;uniform float fade;
   vec2 coord(vec2 q,float panel){return vec2((clamp(q.x,0.,1.)*(size.x-1.)+.5+panel*size.x)/(4.*size.x),(clamp(q.y,0.,1.)*(size.y-1.)+.5)/size.y);}
   float sdf(vec2 q){return (texture2D(atlas,coord(q,2.)).r*2.-1.)*range;}
   float mask(vec2 q){return texture2D(atlas,coord(q,3.)).r;}
   void main(){float d=sdf(uv);float a=mask(uv);float weight;
    if(abs(grow)<.01){weight=a*(feather>.01?smoothstep(0.,feather,max(d,0.)):1.);}
    else{vec2 du=1./size;vec2 grad=vec2(sdf(uv+vec2(du.x,0.))-sdf(uv-vec2(du.x,0.)),sdf(uv+vec2(0.,du.y))-sdf(uv-vec2(0.,du.y)));vec2 near=uv+normalize(grad+vec2(.00001))*max(0.,-d+2.*source.x/size.x)/source;float opacity=max(a,mask(near));weight=(feather>.01?smoothstep(0.,feather,d+grow):step(0.,d+grow))*opacity;}
    gl_FragColor=vec4(mix(texture2D(atlas,coord(uv,0.)).rgb,texture2D(atlas,coord(uv,1.)).rgb,weight*fade),1.);}`;
  const shader=(type,text)=>{const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error('Anteprima GPU non disponibile: '+gl.getShaderInfoLog(s));return s;};
  const program=this.program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Impossibile preparare le anteprime.');gl.useProgram(program);
  this.buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);const p=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
  this.texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,this.texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
  this.u=Object.fromEntries(['size','source','grow','feather','range','fade'].map(k=>[k,gl.getUniformLocation(program,k)]));gl.uniform2f(this.u.size,info.width,info.height);gl.uniform2f(this.u.source,info.source_width,info.source_height);gl.uniform1f(this.u.range,info.field_range);
 }
 draw(video,presets){
  const i=this.info,w=i.width,h=i.height,t=video.currentTime,fade=i.fade>0?clamp(Math.min((t+1/i.fps)/i.fade,(i.duration-t)/i.fade),0,1):1;
  if(this.gl){const gl=this.gl;gl.bindTexture(gl.TEXTURE_2D,this.texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);gl.uniform1f(this.u.fade,fade);
   presets.forEach((p,n)=>{gl.viewport(n*w,0,w,h);gl.uniform1f(this.u.grow,p.grow);gl.uniform1f(this.u.feather,p.feather);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);});
   this.contexts.forEach((c,n)=>c.drawImage(this.output,n*w,0,w,h,0,0,w,h));
  }else{
   this.cpuContext.drawImage(video,0,0);const pixels=this.cpuContext.getImageData(0,0,w*4,h).data;
   presets.forEach((p,n)=>{const frame=this.contexts[n].createImageData(w,h),a=frame.data;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){const q=(y*w*4+x)*4,k=(y*w+x)*4,d=(pixels[q+w*8]/255*2-1)*i.field_range;let z=clamp((d+p.grow)/Math.max(p.feather,.001),0,1),alpha=z*z*(3-2*z);if(!p.grow)alpha*=pixels[q+w*12]/255;alpha*=fade;for(let c=0;c<3;c++)a[k+c]=Math.round(pixels[q+c]*(1-alpha)+pixels[q+w*4+c]*alpha);a[k+3]=255;}this.contexts[n].putImageData(frame,0,0);});
  }
 }
 destroy(){if(this.gl){this.gl.deleteTexture(this.texture);this.gl.deleteBuffer(this.buffer);this.gl.deleteProgram(this.program);this.gl.getExtension('WEBGL_lose_context')?.loseContext();}this.output.width=1;this.output.height=1;}
}
