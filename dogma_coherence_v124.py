"""Color-preserving tile refinement and opt-in single-inference regions."""
import base64
import copy
import math

from .dogma_integrated_v122 import DOGMAChooseCategoriesV122, DOGMAPhase3CropsV122

PROTECTION = {'minima': 1.0, 'bassa': .65, 'media': .35, 'alta': .15}


class DOGMAColorProtectionV124:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'protezione_colore': (list(PROTECTION), {'default': 'alta',
            'tooltip': 'Protegge colore e luminosita: minima=1, bassa=.65, media=.35, alta=.15.'})}}
    RETURN_TYPES = ('FLOAT',)
    RETURN_NAMES = ('low_frequency_strength',)
    FUNCTION = 'value'
    CATEGORY = 'DOGMA/v1.0.24'

    def value(self, protezione_colore):
        return (PROTECTION[protezione_colore],)


class DOGMATileColorProtectV124:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'generated': ('IMAGE',), 'reference': ('IMAGE',),
            'strength': ('FLOAT', {'default': .15, 'min': 0., 'max': 1.})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'protect'
    CATEGORY = 'DOGMA/v1.0.24'

    def protect(self, generated, reference, strength):
        import torch
        import torch.nn.functional as F
        from scipy import ndimage
        if not math.isfinite(strength) or not 0 <= strength <= 1:
            raise ValueError('DOGMA: invalid color protection strength.')
        if generated.shape != reference.shape or generated.shape[-1] != 3:
            raise ValueError('DOGMA: color protection requires corresponding RGB tiles of identical dimensions.')
        if strength == 1:
            return (generated,)
        # Compute only the broad change. Do not normalize or histogram-match the tile.
        reference = reference.to(device=generated.device, dtype=generated.dtype)
        delta = (generated-reference).float().movedim(-1,1)
        h,w = generated.shape[1:3]
        # Fixed spatial scale in render pixels, also for smaller edge tiles.
        ah,aw = max(1,math.ceil(h/4)),max(1,math.ceil(w/4))
        small = F.interpolate(delta,size=(ah,aw),mode='area').detach().cpu().numpy()
        low = ndimage.gaussian_filter(small,sigma=(0,0,4,4),mode='reflect')
        low = F.interpolate(torch.from_numpy(low).to(generated.device),size=(h,w),
                            mode='bilinear',align_corners=False).movedim(1,-1)
        return ((generated.float()-(1-strength)*low).clamp(0,1).to(generated.dtype),)


class DOGMAChooseCategoriesV124(DOGMAChooseCategoriesV122):
    CATEGORY = 'DOGMA/v1.0.24'

    async def choose(self, **kwargs):
        return await super().choose(_supports_avoid_blocks=True, **kwargs)


class DOGMAPhase3CropsV124(DOGMAPhase3CropsV122):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(super().INPUT_TYPES())
        inputs['required']['context_px'][1]['default'] = 256
        inputs['required']['whole_region_side'] = ('INT', {'default': 3072, 'min': 2048, 'max': 3072, 'step': 1024,
            'tooltip': 'Evita Blocchi: lato lungo massimo, rapporto di aspetto preservato. Riduce solo se necessario; nessuna divisione in tile di sampling.'})
        return inputs
    CATEGORY = 'DOGMA/v1.0.24'

    def run(self, selection, whole_region_side=3072, **kwargs):
        if whole_region_side not in (2048,3072):
            raise ValueError('DOGMA: Evita Blocchi requires 2048 or 3072 pixels.')
        bundle,cards,report = super().run(selection, _whole_region_side=whole_region_side, **kwargs)
        bundle['avoid_blocks_by_target'] = dict(selection.get('avoid_blocks_by_target',{}))
        return bundle,cards,report


class WholeRegionCrop:
    """One complete approved instance (or surface union); preserve native placement."""
    def make(self,image,masks,category,kind,target_long_side,group_gap_px,context_px,
             max_objects_per_chunk,max_chunks,mask_threshold):
        import torch
        import torch.nn.functional as F
        limit=int(target_long_side)//32*32
        src=image[:1,...,:3];h,w=src.shape[1:3]
        mask=masks.detach().float().to(src.device)
        if mask.ndim == 2:mask=mask[None]
        full=F.interpolate(mask[:,None],size=(h,w),mode='nearest')[:,0].amax(0)>=mask_threshold
        yy,xx=torch.where(full)
        if not len(xx):
            return [],[],[],f'{category}: empty whole region; no inference.'
        x0=max(0,int(xx.min())-context_px);x1=min(w,int(xx.max())+1+context_px)
        y0=max(0,int(yy.min())-context_px);y1=min(h,int(yy.max())+1+context_px)
        ch,cw=y1-y0,x1-x0
        scale=min(1.,limit/max(ch,cw))
        rh,rw=max(1,round(ch*scale)),max(1,round(cw*scale))
        pb,pr=(-rh)%32,(-rw)%32
        crop=src[:,y0:y1,x0:x1]
        native=full[y0:y1,x0:x1]
        local=native[None,None].float()
        if (rh,rw)!=(ch,cw):
            crop=F.interpolate(crop.movedim(-1,1),size=(rh,rw),mode='bicubic',align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            local=F.interpolate(local,size=(rh,rw),mode='nearest')
        if not bool(local.any()):
            raise ValueError('DOGMA: whole-region downscale lost this thin mask; disable Evita Blocchi for it.')
        crop=F.pad(crop.movedim(-1,1),(0,pr,0,pb),mode='replicate').movedim(1,-1)
        local=F.pad(local[:,0],(0,pr,0,pb))
        import numpy as np
        packed=base64.b64encode(np.packbits(native.cpu().numpy()).tobytes()).decode('ascii')
        meta=dict(x=x0,y=y0,width=cw,height=ch,source_width=w,source_height=h,
            noop=False,group_id=0,members=1,model_mode='whole_region',avoid_blocks=True,
            pad_right=pr,pad_bottom=pb,original_chunk_width=cw,original_chunk_height=ch,
            render_width=rw,render_height=rh,source_mask_packbits=packed)
        assert max(crop.shape[1:3])<=limit
        return [crop],[local],[meta],f'{category}: Evita Blocchi On; 1 inference; source {cw}x{ch} -> render {rw}x{rh}; limit {limit}px.'


NODE_CLASS_MAPPINGS = {c.__name__:c for c in (
    DOGMAColorProtectionV124,DOGMATileColorProtectV124,DOGMAChooseCategoriesV124,DOGMAPhase3CropsV124)}
NODE_DISPLAY_NAME_MAPPINGS = {
    'DOGMAColorProtectionV124':'DOGMA - Protezione colore',
    'DOGMATileColorProtectV124':'DOGMA - Protezione colore tile',
    'DOGMAChooseCategoriesV124':'DOGMA - Categorie / Denoise / Evita Blocchi',
    'DOGMAPhase3CropsV124':'DOGMA - Ritagli nativi o elemento intero',
}
