"""DOGMA 1.0.10: restore text-conditioned SAM refinement, broader coverage,
four-candidate audit sheets and explicit optional audit rejection.
No core changes. Earlier workflow IDs retain their previous behavior.
"""
import json, math, re, sys

PREFIX='DOGMA110_STATE='
BATCH=4
def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]
def old():return sys.modules[node('DOGMASAMSearchV567').__module__]
def support():return sys.modules[node('DOGMASAMSearchBoundedV2').__module__]
def state_from(notes):
    records=[json.loads(s[len(PREFIX):]) for s in notes if s.startswith(PREFIX)]
    return records[-1] if records else {'examined':0}

def detect(model,clip,image,query,threshold,limit,refinement):
    from nodes import CLIPTextEncode
    from comfy_extras.nodes_sam3 import SAM3_Detect
    cond=CLIPTextEncode().encode(clip,query)[0]
    meta=dict(cond[0][1]);entries=meta.get('sam3_multi_cond')
    if entries is None:entries=[dict(cond=cond[0][0],attention_mask=meta.get('attention_mask'))]
    meta['sam3_multi_cond']=[dict(e,max_detections=int(limit)) for e in entries]
    result=SAM3_Detect.execute(model=model,image=image,conditioning=[[cond[0][0],meta]],
        threshold=threshold,refine_iterations=int(refinement),individual_masks=True)
    return result[0],result[1]

def preserve_masks(raw,boxes,h,w,source):
    """Preserve SAM output, including holes and disconnected visible components.
    Only reject malformed, nonfinite or empty/tiny masks, not sparsity/shape ratios.
    Detection boxes never crop the returned masks.
    """
    import torch
    raw=raw.detach().float().cpu()
    if raw.ndim==2:raw=raw[None]
    if raw.ndim!=3 or tuple(raw.shape[1:])!=(h,w) or len(raw)!=len(boxes):
        raise ValueError('DOGMA: SAM masks/boxes shape mismatch.')
    out=[];bad=0
    for i,(mask,box) in enumerate(zip(raw,boxes)):
        if not torch.isfinite(mask).all() or mask.min()<0 or mask.max()>1:
            bad+=1;continue
        m=mask>=.5
        if int(m.sum())<4:bad+=1;continue
        score=float(box.get('score',1))
        if not math.isfinite(score):bad+=1;continue
        out.append(dict(mask=m,score=score,source=f'{source}/{i+1}'))
    return out,bad

class DOGMASAMCoverageV110:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'model':('MODEL',),'clip':('CLIP',),
            'category':('STRING',{'forceInput':True}),'query_hint':('STRING',{'forceInput':True}),
            'mode':(['global','local_recovery'],),'threshold':('FLOAT',{'default':.25,'min':.05,'max':.9,'step':.01}),
            'max_instances':('INT',{'default':32,'min':8,'max':64}),
            'max_queries':('INT',{'default':3,'min':1,'max':4}),
            'recovery_views':('INT',{'default':4,'min':0,'max':4}),
            'refine_iterations':('INT',{'default':4,'min':0,'max':5})},
            'optional':{'previous':('DOGMA_REVIEW',),'after':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('DOGMA_CANDIDATES','STRING');RETURN_NAMES=('candidates','search_report')
    FUNCTION='search';CATEGORY='DOGMA/v1.0.10'
    def search(self,image,model,clip,category,query_hint,mode,threshold,max_instances,max_queries=3,recovery_views=4,refine_iterations=4,previous=None,after=None):
        import torch
        if image.ndim!=4 or image.shape[0]!=1:raise ValueError('DOGMA: one source image required.')
        h,w=image.shape[1:3];category=old().canonical(category)
        if previous and (previous['category']!=category or tuple(previous['shape'])!=(h,w)):raise ValueError('DOGMA: recovery mismatch.')
        if mode=='local_recovery' and previous is None:raise ValueError('DOGMA: first pass missing.')
        accepted=list(previous.get('accepted',[])) if previous else []
        notes=list(previous.get('notes',[])) if previous else []
        state=state_from(notes);items=[];calls=0;invalid=0;seen=0
        # Reserve one quarter for spatial recovery, independently of audit verdicts.
        reserve=min(max_instances//4,int(recovery_views)*2)
        available=max(0,max_instances-state['examined'])
        budget=min(available,max_instances-reserve) if mode=='global' else available
        # Start with the broad family, then explicit scene-specific terms.
        choices=old().queries(category)[:1]+str(query_hint).split(';')+old().queries(category)[1:]
        queries=[]
        for q in choices:
            q=' '.join(str(q).strip().lower().split()[:6])
            if q and not old().inactive(q) and q not in queries:queries.append(q)
        queries=queries[:max_queries]
        if mode=='global':jobs=[(q,(0,0,w,h)) for q in queries]
        else:
            windows=old().local_windows(h,w)[:recovery_views]
            jobs=[(queries[i%len(queries)],r) for i,r in enumerate(windows)] if queries else []
        if not old().inactive(category):
            for ji,(query,(x0,y0,x1,y1)) in enumerate(jobs):
                remaining=budget-seen
                if remaining<=0:break
                cap=max(1,math.ceil(remaining/(len(jobs)-ji)))
                raw,boxes=detect(model,clip,image[:,y0:y1,x0:x1,:3],query,threshold,cap,refine_iterations)
                calls+=1
                if isinstance(boxes,list) and len(boxes)==1 and isinstance(boxes[0],list):boxes=boxes[0]
                if raw.ndim==2:raw=raw[None]
                if not isinstance(boxes,list) or len(boxes)!=len(raw):raise ValueError('DOGMA: detector mask/box mismatch.')
                # If a core implementation ignores max_detections, never crash on overflow.
                order=sorted(range(len(boxes)),key=lambda j:float(boxes[j].get('score',0)),reverse=True)[:cap]
                raw=raw[order];boxes=[boxes[j] for j in order]
                seen+=len(boxes);state['examined']+=len(boxes)
                found,bad=preserve_masks(raw,boxes,y1-y0,x1-x0,f'{mode}/{ji+1}/{query}')
                invalid+=bad
                for item in found:
                    full=torch.zeros((h,w),dtype=torch.bool);full[y0:y1,x0:x1]=item['mask'];item['mask']=full
                items=support().bounded_instances(items+found,accepted,max_instances)
        notes=[s for s in notes if not s.startswith(PREFIX)]+[PREFIX+json.dumps(state)]
        report=(f'{category} / {mode}: text SAM with {refine_iterations} refinement passes; '
            f'{calls} searches; {seen} detections examined, {invalid} invalid/empty, '
            f'{len(items)} nonduplicate masks, {len(accepted)} retained from first pass. '
            f'Cumulative detection cap {state["examined"]}/{max_instances}. '
            'SAM surfaces preserved: no box-only replacement, bbox clipping or shape-ratio rejection. '
            'A search cap can leave objects uncovered; see masks and final coverage report.')
        return dict(category=category,shape=(h,w),items=items,accepted=accepted,notes=notes+[report]),report

class DOGMAAuditBatchV110:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'candidates':('DOGMA_CANDIDATES',),'panel_size':('INT',{'default':384,'min':256,'max':768,'step':64})}}
    RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('instance_sheets','audit_instructions')
    OUTPUT_IS_LIST=(True,True);FUNCTION='build';CATEGORY='DOGMA/v1.0.10'
    def build(self,image,candidates,panel_size=384):
        import numpy as np
        import torch
        import torch.nn.functional as F
        from PIL import Image,ImageDraw,ImageFont
        if not candidates['items']:return [torch.zeros((1,64,64,3))],['No candidates.']
        sheets,_=node('DOGMAInstanceAuditViewV567')().build(image,candidates,min(panel_size,384))
        grids=[];prompts=[];side=512
        for offset in range(0,len(sheets),BATCH):
            chunk=sheets[offset:offset+BATCH];grid=torch.full((1,side*2,side*2,3),.12)
            for j,sheet in enumerate(chunk):
                h,w=sheet.shape[1:3];scale=min((side-40)/h,side/w)
                sh,sw=max(1,round(h*scale)),max(1,round(w*scale))
                tile=F.interpolate(sheet.movedim(-1,1),size=(sh,sw),mode='bilinear',align_corners=False).movedim(1,-1)
                y=(j//2)*side;x=(j%2)*side
                grid[:,y+40:y+40+sh,x+(side-sw)//2:x+(side-sw)//2+sw]=tile
                banner=Image.new('RGB',(side,36),(20,20,20));draw=ImageDraw.Draw(banner)
                try:font=ImageFont.load_default(size=22)
                except TypeError:font=ImageFont.load_default()
                draw.text((10,5),f'{j+1}: {candidates["category"]}',font=font,fill='white')
                grid[:,y:y+36,x:x+side]=torch.from_numpy(np.asarray(banner).copy()).float()/255
            grids.append(grid)
            prompts.append(f'Audit {len(chunk)} numbered candidates for {candidates["category"]}. '
                'Each numbered tile contains original crop, white mask, cyan overlay and selected pixels on gray. '
                'PASS useful selections belonging to the category, including partial objects, holes, occlusions, disconnected visible surfaces and imperfect boundaries. '
                'FAIL only for clearly substantial selection of unrelated objects/background or an absent target. '
                'Do not fail for missing other objects or incomplete coverage. '
                f'Return exactly {len(chunk)} lines in order: 1 PASS or 1 FAIL, then 2 PASS or 2 FAIL, and so on. Add a short reason after each verdict.')
        return grids,prompts

class DOGMAReviewBatchV110:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'candidates':('DOGMA_CANDIDATES',),'audit_text':('STRING',{'forceInput':True}),
        'audit_mode':(['report_only','reject_explicit_fail'],{'default':'report_only'})}}
    RETURN_TYPES=('DOGMA_REVIEW','STRING');RETURN_NAMES=('review','audit_report')
    INPUT_IS_LIST=True;FUNCTION='review';CATEGORY='DOGMA/v1.0.10'
    def review(self,candidates,audit_text,audit_mode):
        if len(candidates)!=1:raise ValueError('DOGMA: exactly one candidate bundle required.')
        data=candidates[0];items=data['items'];accepted=list(data['accepted']);lines=[]
        mode=audit_mode[0] if isinstance(audit_mode,list) else audit_mode
        if mode not in ('report_only','reject_explicit_fail'):raise ValueError('Unknown audit mode')
        if items and len(audit_text)!=math.ceil(len(items)/BATCH):raise ValueError('DOGMA: audit batch count mismatch.')
        for bi,text in enumerate(audit_text):
            votes={};ambiguous=set()
            text=re.sub(r'<think>.*?</think>','',str(text),flags=re.S|re.I)
            for line in text.splitlines():
                match=re.match(r'^\s*(?:[-*]\s*)?(\d+)\s*[.):=-]?\s*(PASS|FAIL)\b',line,re.I)
                if match:
                    ident=int(match[1]);vote=match[2].upper()
                    if ident in votes and votes[ident]!=vote:ambiguous.add(ident)
                    votes[ident]=vote
            for j,item in enumerate(items[bi*BATCH:(bi+1)*BATCH],1):
                vote='REVIEW' if j in ambiguous else votes.get(j,'REVIEW')
                keep=mode=='report_only' or vote!='FAIL'
                if keep:accepted.append(item)
                lines.append(f'{item["source"]}: audit {vote}; {"KEPT" if keep else "REJECTED"}; mode={mode}')
        notes=data['notes']+lines
        result=dict(category=data['category'],shape=data['shape'],accepted=accepted,notes=notes)
        return result,'\n'.join(s for s in notes if not s.startswith(PREFIX))

class DOGMAFinalCoverageV110:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'review':('DOGMA_REVIEW',)}}
    RETURN_TYPES=('MASK','STRING');RETURN_NAMES=('approved_instances','report')
    FUNCTION='finish';CATEGORY='DOGMA/v1.0.10'
    def finish(self,review):
        import torch
        h,w=review['shape'];items=support().bounded_instances(review['accepted'],limit=64)
        masks=torch.stack([i['mask'] for i in items]).float() if items else torch.zeros((0,h,w))
        coverage=float(masks.bool().any(0).float().mean())*100 if len(masks) else 0.
        report=f'{review["category"]}: {len(items)} masks, union covers {coverage:.2f}% of the image. '
        if not items:report+='EMPTY CATEGORY: no retained SAM masks; no semantic render for this category. '
        report+='Coverage is measured, not guaranteed complete.\n'+'\n'.join(s for s in review['notes'] if not s.startswith(PREFIX))
        return masks,report

NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMASAMCoverageV110,DOGMAAuditBatchV110,DOGMAReviewBatchV110,DOGMAFinalCoverageV110)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V110',' v1.0.10') for k in NODE_CLASS_MAPPINGS}
