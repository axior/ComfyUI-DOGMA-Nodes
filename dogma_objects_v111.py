"""Recover object-aware grouping from V54.5 while retaining the hard no-downscale budget."""
import math,sys

def support():
    import nodes
    return sys.modules[nodes.NODE_CLASS_MAPPINGS['DOGMANativeChunkCropsV2'].__module__]

def render_geometry(h,w,target):return support().render_geometry(h,w,target)

def object_windows(masks,union,target,context,max_chunks,gap,max_objects):
    import numpy as np
    h,w=union.shape;mh,mw=masks.shape[-2:];side=max(512,int(target)//32*32)
    groups=[]
    for mask in masks:
        ys,xs=np.nonzero(mask.numpy()>=.5)
        if not len(xs):continue
        box=(int(xs.min()*w/mw),int(ys.min()*h/mh),min(w,math.ceil((xs.max()+1)*w/mw)),min(h,math.ceil((ys.max()+1)*h/mh)))
        groups.append(([box],box))
    def merged(a,b):return min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])
    # Merge nearby objects only when the complete padded group fits the native render budget.
    changed=True
    while changed:
        changed=False
        for i in range(len(groups)):
            for j in range(i+1,len(groups)):
                aa,a=groups[i];bb,b=groups[j];u=merged(a,b)
                distance=max(max(a[0]-b[2],b[0]-a[2],0),max(a[1]-b[3],b[1]-a[3],0))
                if len(aa)+len(bb)<=max_objects and distance<=gap and max(u[2]-u[0],u[3]-u[1])+2*context<=side:
                    groups[i]=(aa+bb,u);groups.pop(j);changed=True;break
            if changed:break
    boxes=[]
    for members,(x0,y0,x1,y1) in groups:
        bw,bh=x1-x0,y1-y0
        if max(bw,bh)<=side:
            px=min(context,(side-bw)//2);py=min(context,(side-bh)//2)
            boxes.append((max(0,x0-px),max(0,y0-py),min(w,x1+px),min(h,y1+py),x0,y0,x1,y1))
        else:
            # An oversized object cannot be rendered whole under the user's no-downscale and VRAM limits.
            local=union[y0:y1,x0:x1]
            windows,_=support().native_windows(local,side,context,100000)
            boxes.extend((a+x0,b+y0,c+x0,d+y0,e+x0,f+y0,g+x0,hh+y0) for a,b,c,d,e,f,g,hh in windows)
    boxes=list(dict.fromkeys(boxes))
    boxes.sort(key=lambda b:(-int(union[b[5]:b[7],b[4]:b[6]].sum()),b[1],b[0]))
    return sorted(boxes[:max_chunks],key=lambda b:(b[1],b[0])),len(boxes)

class DOGMAObjectNativeCropsV111:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'masks':('MASK',),'category':('STRING',{'forceInput':True}),
            'kind':('STRING',{'forceInput':True}),
            'target_long_side':('INT',{'default':2048,'min':512,'max':4096,'step':32}),
            'group_gap_px':('INT',{'default':180,'min':0,'max':1200}),
            'context_px':('INT',{'default':160,'min':32,'max':640,'step':32}),
            'max_objects_per_chunk':('INT',{'default':6,'min':1,'max':20}),
            'max_chunks':('INT',{'default':4,'min':1,'max':24}),
            'mask_threshold':('FLOAT',{'default':.3,'min':.05,'max':.8,'step':.01})}}
    RETURN_TYPES=('IMAGE','MASK','DOGMA_STITCH','STRING')
    RETURN_NAMES=('crops','crop_masks','stitch','info')
    OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION='make'
    CATEGORY='DOGMA/v1.0.11'
    def make(self,image,masks,category,kind,target_long_side,group_gap_px,context_px,max_objects_per_chunk,max_chunks,mask_threshold):
        import numpy as np
        import torch
        import torch.nn.functional as F
        src=image[:1,...,:3];h,w=src.shape[1:3]
        m=masks.detach().float().cpu()
        if m.ndim==2:m=m[None]
        union=torch.zeros((h,w),dtype=torch.bool)
        for mask in m:
            union |= F.interpolate(mask[None,None],size=(h,w),mode='nearest')[0,0]>=mask_threshold
        boxes,total=object_windows(m,union.numpy(),target_long_side,context_px,int(max_chunks),group_gap_px,max_objects_per_chunk)
        if not boxes:
            zero=torch.zeros((1,64,64));empty=torch.zeros((1,64,64,3),dtype=src.dtype,device=src.device)
            return [empty],[zero],[{'noop':True}],f'{category}: no approved region, no diffusion required.'
        crops=[];crop_masks=[];metadata=[];details=[]
        for index,(x0,y0,x1,y1,cx0,cy0,cx1,cy1) in enumerate(boxes):
            crop=src[:,y0:y1,x0:x1];ch,cw=crop.shape[1:3]
            local=union[y0:y1,x0:x1].clone()
            # 32px shared ownership around tile cores, with the remaining context unmodified.
            owner=torch.zeros_like(local)
            owner[max(0,cy0-y0-32):min(ch,cy1-y0+32),max(0,cx0-x0-32):min(cw,cx1-x0+32)]=True
            local=(local&owner)[None].float()
            rh,rw,pb,pr=render_geometry(ch,cw,target_long_side)
            if (rh,rw)!=(ch,cw):
                crop=F.interpolate(crop.movedim(-1,1),size=(rh,rw),mode='bicubic',align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
                local=F.interpolate(local[:,None],size=(rh,rw),mode='nearest')[:,0]
            crop=F.pad(crop.movedim(-1,1),(0,pr,0,pb),mode='replicate').movedim(1,-1)
            local=F.pad(local,(0,pr,0,pb),value=0)
            assert crop.shape[1]>=ch and crop.shape[2]>=cw
            assert max(crop.shape[1:3])<=int(target_long_side)
            crops.append(crop);crop_masks.append(local)
            metadata.append(dict(x=x0,y=y0,width=cw,height=ch,source_width=w,source_height=h,
                noop=False,group_id=index,members=0,model_mode='native_or_upscale_only',
                pad_right=pr,pad_bottom=pb,original_chunk_width=cw,original_chunk_height=ch))
            details.append(f'{index+1}: source {cw}x{ch} -> render {crop.shape[2]}x{crop.shape[1]}')
        info=(f'{category}: {len(boxes)}/{total} object-preserving/native windows; render limit {target_long_side}px, '
              f'budget {max_chunks}. No downscale of any source region. {total-len(boxes)} windows deferred, their pixels preserved. '
              'Whole objects and nearby groups are retained when they fit the render limit; oversized instances alone use spatial windows.\n'+'\n'.join(details))
        return crops,crop_masks,metadata,info

NODE_CLASS_MAPPINGS={'DOGMAObjectNativeCropsV111':DOGMAObjectNativeCropsV111}
NODE_DISPLAY_NAME_MAPPINGS={'DOGMAObjectNativeCropsV111':'DOGMA Object Native Crops v1.0.11'}
