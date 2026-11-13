import {viewURL} from './dogma_h3_media.js?v=studio-1-0-50';
const clamp=(x,a,b)=>Math.min(b,Math.max(a,x));
const el=(tag,cls='')=>{const e=document.createElement(tag);e.className=cls;return e;};
export class RestitchHover{
 constructor(panel,Renderer){
  this.panel=panel;this.Renderer=Renderer;this.abort=new AbortController();this.closed=false;
  this.root=el('div','dg-restitch-hover');this.root.setAttribute('aria-hidden','true');
  this.title=el('strong');this.canvas=el('canvas');this.caption=el('small');this.root.append(this.title,this.canvas,this.caption);
  // Keep the floating preview in the dialog's top layer; it never intercepts clicks.
  panel.root.closest('dialog').append(this.root);
  const signal=this.abort.signal;
  window.addEventListener('keydown',e=>{if(e.key==='Escape'&&this.active){this.hide();e.preventDefault();e.stopPropagation();}},{capture:true,signal});
  window.addEventListener('scroll',()=>this.hide(),{capture:true,passive:true,signal});
  window.addEventListener('resize',()=>this.hide(),{signal});
  window.addEventListener('blur',()=>this.hide(),{signal});
 }
 bind(card,preset,thumbnail){
  const signal=this.abort.signal,show=e=>{
   if(e.pointerType==='touch')return;clearTimeout(this.showTimer);clearTimeout(this.hideTimer);
   this.pointer={x:e.clientX,y:e.clientY};
   this.showTimer=setTimeout(()=>this.show(preset,thumbnail),this.active?0:140);
  };
  card.addEventListener('pointerenter',show,{signal});
  card.addEventListener('pointermove',e=>{this.pointer={x:e.clientX,y:e.clientY};if(this.active)this.follow();},{signal});
  card.addEventListener('pointerleave',()=>{clearTimeout(this.showTimer);this.hideTimer=setTimeout(()=>this.hide(),65);},{signal});
  card.addEventListener('focus',()=>{if(!card.matches(':focus-visible'))return;const r=card.getBoundingClientRect();show({clientX:r.x+r.width/2,clientY:r.y+r.height/2});},{signal});
  card.addEventListener('blur',()=>this.hide(),{signal});
 }
 show(preset,thumbnail){
  if(this.closed||!this.panel.root.open)return;
  this.active={preset,thumbnail};this.title.textContent=preset.label;this.root.dataset.open='true';
  const ratio=this.panel.info.width/this.panel.info.height;
  const viewport=window.visualViewport,w=viewport?.width||innerWidth,h=viewport?.height||innerHeight;
  const width=Math.max(120,Math.min(1080,w*.62,(h*.76-72)*ratio,w-32));
  this.root.style.width=width+'px';this.canvas.style.aspectRatio=ratio;
  this.draw();this.follow(true);this.loadDetail();
 }
 follow(immediate=false){
  if(!this.active)return;const viewport=window.visualViewport,ox=viewport?.offsetLeft||0,oy=viewport?.offsetTop||0;
  const w=viewport?.width||innerWidth,h=viewport?.height||innerHeight,r=this.root.getBoundingClientRect(),p=this.pointer;
  // Anchor opposite the pointer, then add a small, damped vertical follow.
  const left=p.x<w/2?p.x+28:p.x-r.width-28;
  this.target={x:clamp(left,ox+16,ox+w-r.width-16),y:clamp(p.y-r.height*.48,oy+16,oy+h-r.height-16)};
  if(immediate||!this.position){this.position={...this.target};this.place();}
  if(!this.motion)this.motion=requestAnimationFrame(()=>this.tick());
 }
 tick(){this.motion=null;if(!this.active)return;const p=this.position,t=this.target;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches,k=reduced?1:.2;p.x+=(t.x-p.x)*k;p.y+=(t.y-p.y)*k;this.place();
  if(Math.abs(t.x-p.x)+Math.abs(t.y-p.y)>.3)this.motion=requestAnimationFrame(()=>this.tick());
 }
 place(){this.root.style.transform=`translate3d(${this.position.x}px,${this.position.y}px,0)`;}
 async loadDetail(){
  if(this.loading||this.detailInfo||this.detailError||this.closed)return;this.loading=true;
  try{
   const info=await this.panel.job('/dogma/h3/v2/edit/restitch/preview',{session:this.panel.studio.config.session,id:this.panel.item.id,detail:true});
   if(this.closed)return;this.detailInfo=info;this.root.dataset.preparedMs=Math.round(info.elapsed_seconds*1000);const video=this.video=el('video','dg-restitch-source');video.muted=true;video.loop=true;video.playsInline=true;video.preload='auto';this.panel.body.append(video);
   video.addEventListener('loadeddata',()=>{if(this.closed)return;try{this.renderer=new this.Renderer(info,[this.canvas]);this.sync();this.draw();}catch(e){this.detailError=e.message;}},{signal:this.abort.signal});
   video.addEventListener('seeked',()=>{if(!this.closed)this.draw();},{signal:this.abort.signal});
   video.addEventListener('error',()=>{this.detailError='Dettaglio non disponibile';this.draw();},{signal:this.abort.signal});
   video.src=viewURL(info.file);video.load();
  }catch(e){if(!this.closed&&e.name!=='AbortError'){this.detailError=e.message;this.draw();}}
  finally{this.loading=false;}
 }
 sync(){
  const master=this.panel.video,video=this.video;if(!master||!video||!this.renderer||!this.active)return false;
  if(video.seeking)return false;
  if(Math.abs(video.currentTime-master.currentTime)>.075){video.currentTime=master.currentTime;return false;}
  if(master.paused)video.pause();else if(video.paused)video.play().catch(()=>{});
  return video.readyState>=2;
 }
 draw(){
  if(!this.active||this.closed)return;const {preset,thumbnail}=this.active,detail=this.sync(),info=detail?this.detailInfo:this.panel.info;
  if(this.canvas.width!==info.width||this.canvas.height!==info.height){this.canvas.width=info.width;this.canvas.height=info.height;}
  if(detail)this.renderer.draw(this.video,[preset]);else this.canvas.getContext('2d').drawImage(thumbnail,0,0,this.canvas.width,this.canvas.height);
  const t=this.panel.video?.currentTime||0;this.canvas.dataset.time=t.toFixed(6);this.root.dataset.quality=detail?'detail':'grid';
  this.caption.textContent=`${preset.grow>0?'+':''}${preset.grow} px · feather ${preset.feather} px · ${info.width} × ${info.height} · ${t.toFixed(2)} s`+(!detail?(this.detailError?' · Dettaglio non disponibile':' · Preparazione dettaglio…'):'');
 }
 pause(){this.video?.pause();}
 hide(){clearTimeout(this.showTimer);clearTimeout(this.hideTimer);this.active=null;delete this.root.dataset.open;this.pause();cancelAnimationFrame(this.motion);this.motion=null;}
 destroy(){if(this.closed)return;this.closed=true;this.hide();this.abort.abort();this.renderer?.destroy();if(this.video){this.video.removeAttribute('src');this.video.load();this.video.remove();}this.root.remove();}
}
