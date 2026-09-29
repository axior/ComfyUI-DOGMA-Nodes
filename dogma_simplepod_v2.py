"""DOGMA workflow support v2: optional Qwen reference and bounded native refinement.

Adds new node IDs only. Existing DOGMA nodes and saved workflows are untouched.
"""
import importlib
import math
import sys
import json
import hashlib
from pathlib import Path

VERSION = '1.0.8'
NONE = '(none)'
BUDGET_PREFIX = 'DOGMA_V2_AUDITED_BUDGET='

def registry_class(name):
    import nodes
    if name not in nodes.NODE_CLASS_MAPPINGS:
        raise RuntimeError('DOGMA v2 requires the existing node pack containing '+name)
    return nodes.NODE_CLASS_MAPPINGS[name]

def old_module():
    cls=registry_class('DOGMASAMSearchV567')
    return sys.modules[cls.__module__]

class DOGMAOptionalReferenceImageV2:
    @classmethod
    def INPUT_TYPES(cls):
        import nodes
        files=list(nodes.LoadImage.INPUT_TYPES()['required']['image'][0])
        return {'required':{'image':([NONE]+files,{'image_upload':True})}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='load'
    CATEGORY='DOGMA/v2'
    @classmethod
    def VALIDATE_INPUTS(cls,image):
        import nodes
        return True if image==NONE else nodes.LoadImage.VALIDATE_INPUTS(image)
    @classmethod
    def IS_CHANGED(cls,image):
        import nodes
        return NONE if image==NONE else nodes.LoadImage.IS_CHANGED(image)
    def load(self,image):
        import nodes
        return (None,) if image==NONE else (nodes.LoadImage().load_image(image)[0],)

class DOGMAOptionalSaveImageV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'enabled':('BOOLEAN',{'default':True}),
                'images':('IMAGE',{'lazy':True}),
                'filename_prefix':('STRING',{'default':'DOGMA_V2/01_QWEN'})},
                'hidden':{'prompt':'PROMPT','extra_pnginfo':'EXTRA_PNGINFO'}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='save'
    CATEGORY='DOGMA/v2'
    def check_lazy_status(self,enabled,images=None,filename_prefix='',**kwargs):
        return ['images'] if enabled and images is None else []
    def save(self,enabled,images=None,filename_prefix='DOGMA_V2/01_QWEN',prompt=None,extra_pnginfo=None):
        if not enabled:return {'ui':{}}
        import nodes
        return nodes.SaveImage().save_images(images,filename_prefix,prompt,extra_pnginfo)

def reference_plan(prompt,use_reference,reference_image,reference_instruction):
    active=bool(use_reference and reference_image is not None)
    return (prompt+'\n\n'+reference_instruction.strip() if active and reference_instruction.strip() else prompt,active)

class DOGMAQwen21OptionalReferenceV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'clip':('CLIP',),'image':('IMAGE',),'vae':('VAE',),
            'prompt':('STRING',{'multiline':True}), 'negative_prompt':('STRING',{'multiline':True}),
            'resolution':('INT',{'default':0,'min':0,'max':4096,'step':32}),
            'use_reference':('BOOLEAN',{'default':False}),
            'reference_max_side':('INT',{'default':1536,'min':256,'max':4096,'step':32}),
            'reference_instruction':('STRING',{'multiline':True,'default':'Use image 1 as the scene to edit. Use image 2 only as a reference for color grading, lighting and photographic style. Preserve the composition, objects and geometry of image 1; do not copy objects or text from image 2.'})},
            'optional':{'reference_image':('IMAGE',)}}
    RETURN_TYPES=('CONDITIONING','CONDITIONING','LATENT','STRING','STRING')
    RETURN_NAMES=('positive','negative','latent','effective_prompt','reference_status')
    FUNCTION='encode'
    CATEGORY='DOGMA/v2'
    def encode(self,clip,image,vae,prompt,negative_prompt,resolution,use_reference,
               reference_max_side,reference_instruction,reference_image=None):
        prompt,active=reference_plan(prompt,use_reference,reference_image,reference_instruction)
        images={'image_1':image}
        if active:
            import comfy.utils
            ref=reference_image[:1]
            h,w=ref.shape[1:3];scale=min(1.,reference_max_side/max(h,w))
            rh=max(32,int(math.ceil(h*scale/32))*32);rw=max(32,int(math.ceil(w*scale/32))*32)
            ref=comfy.utils.common_upscale(ref.movedim(-1,1),rw,rh,'lanczos','disabled').movedim(1,-1)
            images['image_2']=ref
        from comfy_extras.nodes_qwen import TextEncodeQwenImage21
        out=TextEncodeQwenImage21.execute(clip=clip,prompt=prompt,negative_prompt=negative_prompt,
                                        vae=vae,resolution=resolution,images=images)
        status='Reference ON: image 1 = scene; image 2 = style/light/color.' if active else 'Reference OFF or absent: only image 1 is encoded.'
        return (out[0],out[1],out[2],prompt,status)

def bounded_instances(items,already=(),limit=8):
    """Rank a bounded detector result and remove contained duplicates without a hard error."""
    import numpy as np
    def geom(item):
        m=item['mask'].detach().cpu().numpy().astype(bool,copy=False)
        yy,xx=np.nonzero(m)
        return m,int(len(xx)),(int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1) if len(xx) else (0,0,0,0)
    entries=[(item,geom(item)) for item in items]
    entries.sort(key=lambda x:(-float(x[0].get('score',1))*math.sqrt(x[1][1]),-x[1][1]))
    refs=[geom(i) for i in already];result=[]
    for item,(m,area,a) in entries:
        if len(result)>=limit:break
        if not area:continue
        duplicate=False
        for n,_,b in refs:
            x0,y0,x1,y1=max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])
            if x1>x0 and y1>y0 and np.count_nonzero(m[y0:y1,x0:x1]&n[y0:y1,x0:x1])/area>=.90:
                duplicate=True;break
        if not duplicate:result.append(item);refs.append((m,area,a))
    return result

def spent_budget(notes):
    return sum(int(n[len(BUDGET_PREFIX):]) for n in notes if n.startswith(BUDGET_PREFIX))

class DOGMASAMSearchBoundedV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'model':('MODEL',),'clip':('CLIP',),
            'category':('STRING',{'forceInput':True}),'mode':(['global','local_recovery'],),
            'threshold':('FLOAT',{'default':.25,'min':.05,'max':.9,'step':.01}),
            'max_instances':('INT',{'default':8,'min':1,'max':32}),
            'max_queries':('INT',{'default':2,'min':1,'max':4}),
            'recovery_views':('INT',{'default':2,'min':0,'max':4})},
            'optional':{'previous':('DOGMA_REVIEW',),'after':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('DOGMA_CANDIDATES','STRING')
    RETURN_NAMES=('candidates','search_report')
    FUNCTION='search'
    CATEGORY='DOGMA/v2'
    def search(self,image,model,clip,category,mode,threshold,max_instances,max_queries=2,recovery_views=2,previous=None,after=None):
        import torch
        old=old_module();search_cls=registry_class('DOGMASAMSearchV567')
        if image.ndim!=4 or image.shape[0]!=1:raise ValueError('DOGMA: one source image required.')
        h,w=image.shape[1:3];category=old.canonical(category)
        if previous and (previous['category']!=category or tuple(previous['shape'])!=(h,w)):
            raise ValueError('DOGMA: mismatched recovery image/category.')
        if mode=='local_recovery' and previous is None:raise ValueError('DOGMA: missing first review.')
        notes=list(previous.get('notes',[])) if previous else []
        accepted=list(previous['accepted']) if previous else []
        remaining=max(0,int(max_instances)-spent_budget(notes));items=[];calls=0;truncated=False
        skip=old.inactive(category) or remaining==0 or (mode=='local_recovery' and bool(accepted))
        views=[(0,0,w,h)] if mode=='global' else old.local_windows(h,w)[:int(recovery_views)]
        if not skip:
            for vi,(x0,y0,x1,y1) in enumerate(views):
                if len(items)>=remaining:break
                aliases=old.queries(category)[:int(max_queries)] if mode=='global' else old.queries(category)[:1]
                for query in aliases:
                    capacity=remaining-len(items)
                    if capacity<=0:break
                    raw,boxes=search_cls._detect(model,clip,image[:,y0:y1,x0:x1,:3],query,threshold,capacity)
                    calls+=1
                    # Also cap before cleaning if an older SAM implementation ignores max_detections.
                    boxlist=boxes[0] if isinstance(boxes,list) and len(boxes)==1 and isinstance(boxes[0],list) else boxes
                    if raw.ndim==2:raw=raw[None]
                    if not isinstance(boxlist,list) or len(boxlist)!=len(raw):
                        raise ValueError('DOGMA: SAM mask/box mismatch.')
                    order=sorted(range(len(boxlist)),key=lambda j:float(boxlist[j].get('score',0)),reverse=True)[:capacity]
                    truncated |= len(boxlist)>capacity
                    raw=raw[order];boxlist=[boxlist[j] for j in order]
                    cleaned,failures=old.clean_instances(raw,boxlist,y1-y0,x1-x0,threshold,category,f'{mode}/{vi+1}/{query}')
                    notes.extend(failures)
                    for item in cleaned:
                        full=torch.zeros((h,w),dtype=torch.bool)
                        full[y0:y1,x0:x1]=item['mask'];item['mask']=full
                    items=bounded_instances(items+cleaned,accepted,remaining)
                    truncated |= len(items)>=remaining
        notes.append(BUDGET_PREFIX+str(len(items)))
        report=(f'{category}: {mode}; {calls} SAM calls, {len(items)} candidates; '
                f'audit budget {spent_budget(notes)}/{max_instances} per category across both passes. '
                f'{len(accepted)} already approved. Recovery runs only if nothing was approved and budget remains. '
                +('Budget reached: other regions stay unchanged. ' if truncated or remaining==0 else '')
                +'This is a bounded selection, not an exhaustive inventory.')
        bundle=dict(category=category,shape=(h,w),items=items,accepted=accepted,notes=notes+[report])
        return bundle,report

class DOGMAFinalMasksBoundedV2:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'review':('DOGMA_REVIEW',)}}
    RETURN_TYPES=('MASK','STRING')
    RETURN_NAMES=('approved_instances','report')
    FUNCTION='finish'
    CATEGORY='DOGMA/v2'
    def finish(self,review):
        import torch
        items=bounded_instances(review['accepted'],limit=32);h,w=review['shape']
        masks=torch.stack([i['mask'] for i in items]).float() if items else torch.zeros((0,h,w))
        summary=f"{review['category']}: {len(items)} verified masks. "
        if not items:summary+='No verified candidate: category skipped, source pixels preserved. '
        return masks,summary+'\n'+'\n'.join(review['notes'])

def native_windows(union,tile_side,context_px,max_chunks):
    """Bound native-coordinate windows BEFORE resizing. Stable priority by mask coverage."""
    import numpy as np
    h,w=union.shape;ys,xs=np.nonzero(union)
    if not len(xs):return [],0
    side=max(512,int(tile_side)//32*32)
    context=min((side-128)//2,int(math.ceil(context_px/32))*32)
    core=max(64,(side-2*context)//32*32)
    x0,y0=int(xs.min())//32*32,int(ys.min())//32*32
    xend,yend=int(xs.max())+1,int(ys.max())+1
    windows=[]
    # Compact selections need only one patch, with full visual context.
    if xend-x0<=core and yend-y0<=core:
        windows=[(max(0,x0-context),max(0,y0-context),min(w,xend+context),min(h,yend+context),x0,y0,xend,yend)]
    else:
        for y in range(y0,yend,core):
            for x in range(x0,xend,core):
                ex,ey=min(w,x+core),min(h,y+core)
                if not union[y:ey,x:ex].any():continue
                windows.append((max(0,x-context),max(0,y-context),min(w,ex+context),min(h,ey+context),x,y,ex,ey))
    windows.sort(key=lambda b:(-int(union[b[5]:b[7],b[4]:b[6]].sum()),b[5],b[4]))
    total=len(windows)
    return sorted(windows[:max_chunks],key=lambda b:(b[1],b[0])),total

def render_geometry(h,w,target):
    scale=max(1.,min(2.,target/max(h,w)))
    rh,rw=min(target,math.ceil(h*scale-1e-9)),min(target,math.ceil(w*scale-1e-9))
    return rh,rw,(-rh)%32,(-rw)%32

class DOGMANativeChunkCropsV2:
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
    CATEGORY='DOGMA/v2'
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
        boxes,total=native_windows(union.numpy(),target_long_side,context_px,int(max_chunks))
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
        info=(f'{category}: {len(boxes)}/{total} native spatial windows; render limit {target_long_side}px, '
              f'budget {max_chunks}. No downscale of any source region. {total-len(boxes)} windows deferred, their pixels preserved. '
              'Grouping-by-object limits are superseded by the spatial tile budget.\n'+'\n'.join(details))
        return crops,crop_masks,metadata,info

class DOGMAPadImageMask32V2:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'mask':('MASK',)}}
    RETURN_TYPES=('IMAGE','INT','INT','MASK')
    FUNCTION='pad'
    CATEGORY='DOGMA/v2'
    def pad(self,image,mask):
        import torch.nn.functional as F
        h,w=image.shape[1:3]
        if mask.shape[-2:]!=(h,w):raise ValueError('DOGMA: image/mask geometry mismatch before VAE.')
        pr,pb=(-w)%32,(-h)%32
        image=F.pad(image.movedim(-1,1),(0,pr,0,pb),mode='replicate').movedim(1,-1)
        return image,w+pr,h+pb,F.pad(mask,(0,pr,0,pb),value=0)

class DOGMAFitDimensions32V2:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'long_side':('INT',{'default':3840,'min':32,'max':16384,'step':32})}}
    RETURN_TYPES=('INT','INT')
    RETURN_NAMES=('width','height')
    FUNCTION='size'
    CATEGORY='DOGMA/v2'
    def size(self,image,long_side):
        h,w=image.shape[1:3]
        return max(32,round(long_side*w/max(h,w)/32)*32),max(32,round(long_side*h/max(h,w)/32)*32)

class DOGMAMaskOwnershipBoundedV2:
    @classmethod
    def INPUT_TYPES(cls):
        req={}
        for i in range(1,6):
            req[f'mask_{i}']=('MASK',);req[f'category_{i}']=('STRING',{'forceInput':True})
        return {'required':req}
    RETURN_TYPES=('MASK',)*5+('STRING',)
    RETURN_NAMES=tuple(f'mask_{i}' for i in range(1,6))+('ownership_report',)
    FUNCTION='resolve'
    CATEGORY='DOGMA/v2'
    def resolve(self,**kwargs):
        import torch
        old=old_module()
        masks=[kwargs[f'mask_{i}'].detach().cpu()>=.5 for i in range(1,6)]
        cats=[old.canonical(kwargs[f'category_{i}']) for i in range(1,6)]
        shape=masks[0].shape[-2:]
        if any(m.ndim!=3 or m.shape[-2:]!=shape for m in masks):raise ValueError('DOGMA: ownership geometry mismatch.')
        def priority(i):
            if cats[i]=='people':return 0
            if cats[i]=='vehicles':return 1
            if old.structural(cats[i]):return 3
            if cats[i] in {'road','ground','pavement','floor','water','grass','vegetation','sky'}:return 4
            return 2
        occupied=torch.zeros(shape,dtype=torch.bool);out=[None]*5;report=[]
        for i in sorted(range(5),key=priority):
            m=masks[i]&~occupied
            if m.numel():m=m[m.flatten(1).sum(1)>=9]
            if len(m):occupied |= m.any(0)
            out[i]=m.float()
            report.append(f'{cats[i]}: {len(m)} non-overlapping instances. '+
                          ('Fully occluded/empty category skipped; ownership retained by earlier categories.' if not len(m) else ''))
        return (*out,'\n'.join(report))

NODE_CLASS_MAPPINGS={c.__name__:c for c in [DOGMAOptionalReferenceImageV2,DOGMAQwen21OptionalReferenceV2,
    DOGMASAMSearchBoundedV2,DOGMAFinalMasksBoundedV2,DOGMANativeChunkCropsV2,DOGMAPadImageMask32V2,DOGMAMaskOwnershipBoundedV2,DOGMAOptionalSaveImageV2,DOGMAFitDimensions32V2]}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V2',' v2') for k in NODE_CLASS_MAPPINGS}
