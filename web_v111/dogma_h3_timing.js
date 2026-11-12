export function frameTime(meta,index){
 if(meta.frame_times)return index>=meta.frame_times.length?meta.duration:meta.frame_times[Math.max(0,index)];
 return index/meta.fps;
}
export const frameCount=meta=>meta.frame_times?.length??Math.floor(meta.duration*meta.fps+1e-6);
export function frameIndex(meta,time){
 if(!meta.frame_times)return Math.max(0,Math.min(frameCount(meta),Math.floor(time*meta.fps+.5)));
 let lo=0,hi=meta.frame_times.length;
 while(lo<hi){const mid=(lo+hi)>>1;if(frameTime(meta,mid)<time)lo=mid+1;else hi=mid;}
 if(lo>0&&time-frameTime(meta,lo-1)<frameTime(meta,lo)-time)lo--;
 return lo;
}
export function snapSelection(start,end,meta,side='end'){
 const total=frameCount(meta);let a=Math.max(0,Math.min(total-1,frameIndex(meta,start))),b=Math.max(1,Math.min(total,frameIndex(meta,end)));
 if(side==='start')a=Math.min(a,b-1);else b=Math.max(b,a+1);
 return {start:frameTime(meta,a),end:frameTime(meta,b)};
}
export function stepTime(meta,time,delta){
 return frameTime(meta,Math.max(0,Math.min(frameCount(meta)-1,frameIndex(meta,time)+delta)));
}
export function parseSeconds(value){
 const s=value.trim().replace(',','.');
 return /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(s)?Number(s):NaN;
}
