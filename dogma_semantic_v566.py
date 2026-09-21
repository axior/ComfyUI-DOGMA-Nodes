"""DOGMA 1.0.5: grounded crop captions and bounded semantic restoration.

New node IDs preserve the behaviour of existing workflows. No model downloads,
filesystem mutations, or global monkey patches are performed by this module.
"""
import math
import re

import numpy as np
import torch
import torch.nn.functional as F
from scipy import ndimage


def _text(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def _kind(category):
    words=set(re.findall(r"[a-z]+", str(category).lower()))
    if words & {'building','buildings','architecture','facade','facades','cathedral','bridge','tower','house','houses'}:
        return 'STRUCTURE'
    if words & {'road','roads','pavement','floor','floors','ground','water','sky','clouds','vegetation','grass','wall','walls'}:
        return 'SURFACE'
    return 'OBJECT'


class DOGMADenoiseCategoryV566:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'category': ('STRING', {'forceInput': True}), 'project_context': ('STRING', {'forceInput': True})}}
    RETURN_TYPES=('STRING','STRING','STRING')
    RETURN_NAMES=('kind','caption_instruction','info')
    FUNCTION='build'
    CATEGORY='DOGMA/v56.6'

    def build(self,category,project_context):
        category=_text(category)
        instruction=(
            'Describe the visible contents of this exact photographic crop in factual English, 60 to 110 words. '
            f'The segmentation target is {category}; describe it only where actually visible, together with the nearby scene. '
            'Describe subject appearance, colors, materials, framing, relative positions, occlusion and observable lighting. '
            'Describe partial objects as partial. Mention people and vehicles only when visible. '
            'Do not infer invisible objects, identity, vehicle make, camera, date, location or exact counts when unclear. '
            'Transcribe lettering only if fully legible. Output only a declarative scene description. '
            'No restoration requests, editing instructions, preserve/keep/refine commands, quality tags or reference-image wording.'
        )
        return (_kind(category),instruction,'Per-crop visual caption required; no fixed category edit prompt.')


class DOGMAChunkPromptV566:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'caption': ('STRING', {'forceInput': True}), 'project_context': ('STRING', {'forceInput': True})}}
    RETURN_TYPES=('STRING',)
    RETURN_NAMES=('prompt',)
    FUNCTION='build'
    CATEGORY='DOGMA/v56.6'

    @staticmethod
    def _declarative(value):
        value=re.sub(r'<think>.*?</think>', '', str(value), flags=re.S|re.I)
        value=re.sub(r'^(?:caption|description|scene)\s*:\s*', '', value.strip(), flags=re.I)
        value=value.strip('` \n')
        sentences=re.split(r'(?<=[.!?])\s+|\n+',value)
        imperative=re.compile(r'^(?:(?:please|only|always|never|do not|don\x27t)\s+)?(?:preserve|keep|refine|restore|enhance|improve|repair|remove|add|avoid|maintain|retain|recover|change|replace|use)\b',re.I)
        return ' '.join(s.strip() for s in sentences if s.strip() and not imperative.search(s.strip()))

    def build(self,caption,project_context):
        caption=self._declarative(caption)
        if len(caption.split())<4:
            raise ValueError('DOGMA: missing factual crop caption. Check the Qwen output before sampling.')
        context=self._declarative(project_context)
        return (' '.join(x for x in [caption,context,'Natural photographic detail, clearly resolved material texture, balanced tonal transitions and restrained local contrast.'] if x),)


class DOGMASAMInstanceGuardV566:
    """Preserve per-instance ownership; reject unpaired or unusable detections.

    SAM3's binary refined mask can include coarse-mask pixels outside its box.
    Bounding boxes must come from the SAME SAM3_Detect call, on the SAME image.
    Geometry cleanup is followed by a separate visual semantic audit.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'masks': ('MASK',), 'bboxes': ('BOUNDING_BOX',), 'image': ('IMAGE',),
            'category': ('STRING', {'forceInput': True}),
            'min_score': ('FLOAT', {'default': .35,'min':0.,'max':1.,'step':.01})}}
    RETURN_TYPES=('MASK','STRING')
    RETURN_NAMES=('bounded_instances','report')
    FUNCTION='clean'
    CATEGORY='DOGMA/v56.6'

    def clean(self,masks,bboxes,image,category,min_score=.35):
        h,w=image.shape[1:3]
        empty=torch.zeros((0,h,w),dtype=torch.float32)
        m=masks.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.ndim!=3 or tuple(m.shape[-2:])!=(h,w):
            return (empty,'SKIP: mask/image dimensions do not match the SAM input.')
        if image.shape[0]!=1:
            return (empty,'SKIP: one source image is required for instance/box pairing.')
        if _text(category).lower() in {'','none','__none__','unused','n/a'}:
            return (empty,'SKIP: unused category.')
        boxes=bboxes
        if isinstance(boxes,list) and len(boxes)==1 and isinstance(boxes[0],list):boxes=boxes[0]
        if not isinstance(boxes,list) or len(boxes)!=m.shape[0] or not all(isinstance(b,dict) for b in boxes):
            return (empty,'SKIP: SAM instance/box count mismatch; refusing to guess ownership.')
        kept=[];notes=[];removed=0
        for i,(mask,box) in enumerate(zip(m,boxes),1):
            try:
                x,y,bw,bh=[float(box[k]) for k in ('x','y','width','height')]
                score=float(box['score'])
                if not all(math.isfinite(v) for v in (x,y,bw,bh,score)) or bw<=0 or bh<=0 or score<min_score:
                    notes.append(f'{i}: low score/invalid box');continue
                x0=max(0,min(w,int(math.floor(x))));y0=max(0,min(h,int(math.floor(y))))
                x1=max(0,min(w,int(math.ceil(x+bw))));y1=max(0,min(h,int(math.ceil(y+bh))))
                if x1<=x0 or y1<=y0:raise ValueError('empty box')
            except (KeyError,TypeError,ValueError,OverflowError):
                notes.append(f'{i}: invalid box');continue
            # MASK inputs are probabilities/binary, never raw logits.
            if not torch.isfinite(mask).all() or mask.min()<0 or mask.max()>1:
                notes.append(f'{i}: invalid mask values');continue
            binary=(mask.numpy()>=.5)
            original=int(binary.sum());roi=binary[y0:y1,x0:x1].copy()
            labels,count=ndimage.label(roi,structure=np.ones((3,3),dtype=np.uint8))
            if not count:notes.append(f'{i}: empty inside box');continue
            sizes=np.bincount(labels.ravel());sizes[0]=0;largest=int(sizes.max())
            minimum=max(4,int(largest*.01))
            chosen=np.flatnonzero(sizes>=minimum)
            filtered=np.isin(labels,chosen)
            before=int(roi.sum());after=int(filtered.sum())
            # A near-frame mask made primarily of scattered islands is unreliable.
            diffuse=(bw*bh/(h*w)>.35 and largest/max(1,before)<.35)
            if after<9 or diffuse:
                notes.append(f'{i}: empty/tiny or diffuse detection');continue
            result=np.zeros((h,w),dtype=bool);result[y0:y1,x0:x1]=filtered
            # Retain holes and disconnected substantial fragments; never dilate/fill.
            kept.append(torch.from_numpy(result));removed+=max(0,original-after)
        output=torch.stack(kept).float() if kept else empty
        coverage=float(output.amax(0).mean())*100 if kept else 0.
        msg=f'{category}: {len(kept)}/{len(boxes)} bounded instances; removed {removed} out-of-box/speckle pixels; union {coverage:.2f}%. '
        return (output,msg+'; '.join(notes))


class DOGMAMaskAuditViewV566:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'masks':('MASK',),'category':('STRING',{'forceInput':True}),
            'panel_size':('INT',{'default':640,'min':256,'max':1024,'step':64})}}
    RETURN_TYPES=('IMAGE','STRING')
    RETURN_NAMES=('audit_sheet','audit_instruction')
    FUNCTION='build'
    CATEGORY='DOGMA/v56.6'

    def build(self,image,masks,category,panel_size=640):
        src=image[:1,...,:3].detach().float().cpu().clamp(0,1);h,w=src.shape[1:3]
        m=masks.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        union=m.amax(0,keepdim=True) if m.numel() else torch.zeros((1,h,w))
        union=F.interpolate(union[:,None],size=(h,w),mode='nearest')[:,0]>=.5
        mask=union[...,None].float();cyan=torch.tensor([.1,.9,1.]).view(1,1,1,3)
        panels=[src,mask.expand(-1,-1,-1,3),src*(1-mask*.65)+cyan*mask*.65,src*mask+.25*(1-mask)]
        scale=min(1.,panel_size/max(h,w));size=(max(16,round(h*scale)),max(16,round(w*scale)))
        small=[F.interpolate(x.movedim(-1,1),size=size,mode='bilinear',align_corners=False).movedim(1,-1) for x in panels]
        sheet=torch.cat([torch.cat(small[:2],2),torch.cat(small[2:],2)],1)
        prompt=(f'Audit the segmentation for category "{_text(category)}". This is a 2 by 2 sheet: '
            'top left original photograph; top right exact white selection on black; '
            'bottom left cyan selection overlay; bottom right selected original pixels on gray. '
            'Check ALL selected regions, including small disconnected patches. '
            'FAIL if the selection contains substantial unrelated sky, buildings, ground or objects, '
            'or scattered islands on unrelated surfaces. For vehicles, road and buildings are not vehicles. '
            'FAIL if the category is absent, the mask is empty, or you cannot judge its semantic correctness. '
            'PASS if selected pixels belong to the named visible category; missing some instances and small edge errors are acceptable. '
            'Return exactly one word: PASS or FAIL. No explanation.')
        return (sheet,prompt)


class DOGMAMaskAuditGateV566:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'masks':('MASK',),'audit_text':('STRING',{'forceInput':True}),
            'category':('STRING',{'forceInput':True}),'geometry_report':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('MASK','STRING')
    RETURN_NAMES=('approved_masks','report')
    FUNCTION='gate'
    CATEGORY='DOGMA/v56.6'

    def gate(self,masks,audit_text,category,geometry_report):
        verdict=str(audit_text).strip().upper()
        ok=verdict=='PASS' and masks.numel()>0 and bool((masks>=.5).any()) and _text(category).lower() not in {'none','__none__',''}
        output=masks.detach().float().cpu().contiguous() if ok else torch.zeros_like(masks,device='cpu',dtype=torch.float32)
        return (output,f'{category}: {"PASS" if ok else "SKIP"}; visual audit={verdict[:100]!r}. {geometry_report}')


class DOGMADualMaskV566:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'mask':('MASK',),'kind':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('MASK','MASK','IMAGE','IMAGE','STRING')
    RETURN_NAMES=('inpaint_mask','blend_mask','inpaint_preview','blend_preview','info')
    FUNCTION='build'
    CATEGORY='DOGMA/v56.6'

    def build(self,mask,kind):
        if mask.ndim==2:mask=mask[None]
        seed=(mask.float()>=.5).float()[:,None]
        radius=min(32,max(8,round(min(mask.shape[-2:])*.012)))
        size=2*radius+1
        wide=F.max_pool2d(seed,(1,size),1,(0,radius))
        wide=F.max_pool2d(wide,(size,1),1,(radius,0))
        blend=seed[:,0];inp=wide[:,0]
        return (inp,blend,inp[...,None].expand(-1,-1,-1,3),blend[...,None].expand(-1,-1,-1,3),
            f'Exact approved ownership: no closing, hole filling or blend growth. Noise support +{radius}px only.')


class DOGMAMaskedDenoiseLatentV566:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'positive':('CONDITIONING',),'negative':('CONDITIONING',),'vae':('VAE',),
            'pixels':('IMAGE',),'mask':('MASK',),'noise_mask':('BOOLEAN',{'default':True}),
            'tile_size':('INT',{'default':3136,'min':512,'max':4096,'step':64}),
            'overlap':('INT',{'default':128,'min':64,'max':512,'step':32})}}
    RETURN_TYPES=('CONDITIONING','CONDITIONING','LATENT')
    RETURN_NAMES=('positive','negative','latent')
    FUNCTION='encode'
    CATEGORY='DOGMA/v56.6'

    def encode(self,positive,negative,vae,pixels,mask,noise_mask=True,tile_size=3136,overlap=128):
        pixels=pixels[...,:3].float()
        if pixels.shape[1]%16 or pixels.shape[2]%16:
            raise ValueError('DOGMA denoise crops must be padded to multiples of 16; refusing a shifted VAE crop.')
        samples=vae.encode_tiled(pixels,tile_x=int(tile_size),tile_y=int(tile_size),overlap=int(overlap))
        latent={'samples':samples}
        if noise_mask:
            m=mask.reshape(-1,1,*mask.shape[-2:]).float()
            latent['noise_mask']=F.interpolate(m,size=pixels.shape[1:3],mode='bilinear',align_corners=False).clamp(0,1)
        return (positive,negative,latent)


class DOGMASoftStitchV566:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'base_image':('IMAGE',),'patches':('IMAGE',),'generation_masks':('MASK',),
            'blend_masks':('MASK',),'stitch':('DOGMA_STITCH',),'category':('STRING',{'forceInput':True}),
            'kind':('STRING',{'forceInput':True}),
            'low_frequency_strength':('FLOAT',{'default':.15,'min':0.,'max':1.,'step':.05})}}
    RETURN_TYPES=('IMAGE','STRING')
    RETURN_NAMES=('image','info')
    INPUT_IS_LIST=True
    FUNCTION='stitch_regions'
    CATEGORY='DOGMA/v56.6'

    @staticmethod
    def alpha_from_seed(seed,width):
        # Pad with background so a mask touching all four edges still has a border.
        distance=ndimage.distance_transform_edt(np.pad(seed.astype(bool),1))[1:-1,1:-1]
        t=np.clip((distance-1.)/max(1.,float(width)),0,1)
        return (t*t*(3-2*t)).astype(np.float32)

    def stitch_regions(self,base_image,patches,generation_masks,blend_masks,stitch,category,kind,low_frequency_strength=.15):
        base=base_image[0] if isinstance(base_image,list) else base_image
        result=base.clone()[...,:3];dev=result.device
        strength=float(low_frequency_strength[0] if isinstance(low_frequency_strength,list) else low_frequency_strength)
        if not(len(patches)==len(generation_masks)==len(blend_masks)==len(stitch)):
            raise ValueError('DOGMA: crop/mask/stitch counts differ; refusing list misalignment.')
        used=0
        for patch,gm,bm,meta in zip(patches,generation_masks,blend_masks,stitch):
            if not meta or meta.get('noop'):continue
            x,y,w,h=[int(meta[k]) for k in ('x','y','width','height')]
            if min(x,y)<0 or min(w,h)<=0 or x+w>result.shape[2] or y+h>result.shape[1]:
                raise ValueError('DOGMA: stitch coordinates outside the source image.')
            if patch.ndim==3:patch=patch[None]
            if bm.ndim==2:bm=bm[None]
            if gm.ndim==2:gm=gm[None]
            pr,pb=int(meta.get('pad_right',0)),int(meta.get('pad_bottom',0))
            if pr:patch=patch[:,:,:-pr];bm=bm[:,:,:-pr];gm=gm[:,:,:-pr]
            if pb:patch=patch[:,:-pb];bm=bm[:,:-pb];gm=gm[:,:-pb]
            patch=F.interpolate(patch[...,:3].float().movedim(-1,1),size=(h,w),mode='bicubic',align_corners=False,antialias=True).movedim(1,-1).to(dev).clamp(0,1)
            # Nearest interpolation cannot create ownership from fractional tails.
            seed=(F.interpolate(bm[:,None].float(),size=(h,w),mode='nearest')[0,0]>=.5).cpu().numpy()
            support=(F.interpolate(gm[:,None].float(),size=(h,w),mode='nearest')[0,0]>=.5).cpu().numpy()
            seed &= support
            alpha=torch.from_numpy(self.alpha_from_seed(seed,min(24,max(4,min(h,w)*.01)))).to(dev)[None,:,:,None]
            region=result[:,y:y+h,x:x+w,:]
            delta=(patch-region).float()
            # Preserve source exposure/color gradients while retaining generated fine detail.
            ah=max(8,round(h*min(1.,512/max(h,w))));aw=max(8,round(w*min(1.,512/max(h,w))))
            small=F.interpolate(delta.movedim(-1,1),size=(ah,aw),mode='area')[0].cpu().numpy()
            low=ndimage.gaussian_filter(small,sigma=(0,4,4),mode='reflect')
            low=F.interpolate(torch.from_numpy(low)[None].to(dev),size=(h,w),mode='bilinear',align_corners=False).movedim(1,-1)
            corrected=region+delta-(1.-strength)*low
            result[:,y:y+h,x:x+w,:]=torch.where(alpha>0,(region+alpha*(corrected-region)).clamp(0,1),region)
            used+=1
        return (result,f'v56.6: {used} crops; distance feather reaches zero at boundary; exact source outside approved ownership; low-frequency change retained {strength:.2f}.')


NODE_CLASS_MAPPINGS={cls.__name__:cls for cls in (
    DOGMADenoiseCategoryV566,DOGMAChunkPromptV566,DOGMASAMInstanceGuardV566,
    DOGMAMaskAuditViewV566,DOGMAMaskAuditGateV566,DOGMADualMaskV566,
    DOGMAMaskedDenoiseLatentV566,DOGMASoftStitchV566)}
NODE_DISPLAY_NAME_MAPPINGS={name:name.replace('DOGMA','DOGMA ').replace('V566',' v56.6') for name in NODE_CLASS_MAPPINGS}
