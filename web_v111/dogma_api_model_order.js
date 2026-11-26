// Reorder only the model blocks. Controls and expansion state stay on their DOM nodes.
export function modelReorder(container,saveOrder){
 let active=null,frame=0,suppressClick=false,scroller=null;
 const models=()=>[...container.children].filter(e=>e.dataset.modelKey);
 const inside=()=>{
  const r=container.getBoundingClientRect(),s=scroller.getBoundingClientRect();
  return active.x>=r.left&&active.x<=r.right&&active.y>=Math.max(r.top,s.top)&&active.y<=Math.min(r.bottom,s.bottom);
 };
 const place=()=>{
  if(!inside())return;
  const next=models().find(row=>{
   if(row===active.row)return false;
   const r=row.querySelector('.dap-model-head>details>summary').getBoundingClientRect();
   return active.y<r.top+r.height/2;
  });
  if(active.row.nextElementSibling!==next&&(next||active.row!==container.lastElementChild))container.insertBefore(active.row,next||null);
 };
 const scroll=()=>{
  if(!active?.dragging)return;
  if(!container.isConnected){finish(false);return;}
  const r=scroller.getBoundingClientRect();
  if(active.x>=r.left&&active.x<=r.right){
   const delta=active.y<r.top+36?-Math.min(12,(r.top+36-active.y)/3):active.y>r.bottom-36?Math.min(12,(active.y-r.bottom+36)/3):0;
   if(delta){scroller.scrollTop+=delta;place();}
  }
  frame=requestAnimationFrame(scroll);
 };
 const finish=(commit=false)=>{
  if(!active)return;
  const {row,original,dragging,pointerId}=active;
  active=null;cancelAnimationFrame(frame);row.classList.remove('dap-model-dragging');
  document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',cancel);
  document.removeEventListener('keydown',key,true);window.removeEventListener('blur',cancel);
  if(container.hasPointerCapture(pointerId))container.releasePointerCapture(pointerId);
  if(!dragging)return;
  suppressClick=true;setTimeout(()=>suppressClick=false,0);
  if(!commit){for(const item of original)container.append(item);return;}
  const order=models().map(item=>item.dataset.modelKey);
  if(order.some((value,i)=>value!==original[i].dataset.modelKey))saveOrder(order);
 };
 const move=e=>{
  if(!active||e.pointerId!==active.pointerId)return;
  active.x=e.clientX;active.y=e.clientY;
  if(!active.dragging){
   if(Math.hypot(e.clientX-active.startX,e.clientY-active.startY)<6)return;
   active.dragging=true;container.setPointerCapture(e.pointerId);active.row.classList.add('dap-model-dragging');frame=requestAnimationFrame(scroll);
  }
  e.preventDefault();place();
 };
 const up=e=>{if(active&&e.pointerId===active.pointerId){active.x=e.clientX;active.y=e.clientY;if(active.dragging)e.preventDefault();finish(inside());}};
 const cancel=()=>finish(false);
 const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();cancel();}};
 container.addEventListener('pointerdown',e=>{
  if(e.button!==0||e.pointerType==='touch'||active)return;
  const summary=e.target.closest('.dap-model-head>details>summary');
  if(!summary||!container.contains(summary))return;
  scroller=container.closest('.dap-side');if(!scroller)return;
  active={row:summary.closest('.dap-model'),original:models(),pointerId:e.pointerId,startX:e.clientX,startY:e.clientY,x:e.clientX,y:e.clientY,dragging:false};
  document.addEventListener('pointermove',move,{passive:false});document.addEventListener('pointerup',up);document.addEventListener('pointercancel',cancel);
  document.addEventListener('keydown',key,true);window.addEventListener('blur',cancel);
 });
 container.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopPropagation();}},true);
 container.addEventListener('dragstart',e=>{if(active)e.preventDefault();});
 container.classList.add('dap-models-sortable');
}
