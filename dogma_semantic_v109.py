"""DOGMA 1.0.9: bounded box-prompt segmentation and specific scene queries.

No core monkey patches, hole filling, mask dilation or union with raw detector masks.
Old workflow node IDs retain their original behavior.
"""
import math
import re
import json
import sys

PREFIX = 'DOGMA109_STATE='

def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]

def old():
    return sys.modules[node('DOGMASAMSearchV567').__module__]

def support():
    return sys.modules[node('DOGMASAMSearchBoundedV2').__module__]

def query_list(category,hint,limit):
    result=[]
    for text in str(hint).split(';')+old().queries(category):
        text=re.sub(r'[^a-zA-Z0-9 -]',' ',text).strip().lower()
        text=' '.join(text.split()[:6])
        if text and text not in result and not old().inactive(text):result.append(text)
    return result[:int(limit)]

class DOGMASemanticPlanV109:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'planner_text':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('STRING',)+('STRING','STRING','FLOAT')*5
    RETURN_NAMES=('plan_preview',)+tuple(x for i in range(1,6) for x in (f'category_{i}',f'sam_prompt_{i}',f'sam_threshold_{i}'))
    FUNCTION='build';CATEGORY='DOGMA/v1.0.9'
    def build(self,planner_text):
        rows=[]
        for line in str(planner_text).splitlines():
            line=re.sub(r'^\s*(?:[-*]|\d+[.)])\s*','',line).strip(' `')
            cat,sep,hint=line.partition('|');cat=old().canonical(cat)
            if old().inactive(cat) or len(cat.split())>4:continue
            if re.search(r'\b(noise|blur|artifact|background|foreground|quality|signage|text)\b',cat):continue
            queries=query_list(cat,hint if sep else cat,3)
            existing=next((r for r in rows if r[0]==cat),None)
            if existing:
                existing[1][:]=list(dict.fromkeys(existing[1]+queries))[:3]
            else:rows.append([cat,queries])
        if not rows:raise ValueError('DOGMA: no usable scene categories; inspect planner output.')
        rows=rows[:5];out=[]
        for cat,queries in rows+[['none',[]]]*(5-len(rows)):out.extend([cat,'; '.join(queries),.25])
        return ('Scene-specific queries (not a coverage guarantee):\n'+'\n'.join(f'{c} | {"; ".join(q)}' for c,q in rows),*out)

def box_geometry(box,h,w):
    values=[float(box[k]) for k in ('x','y','width','height','score')]
    x,y,bw,bh,score=values
    if not all(math.isfinite(v) for v in values) or min(bw,bh)<=0:raise ValueError('Invalid detector box')
    x0,y0=max(0,math.floor(x)),max(0,math.floor(y))
    x1,y1=min(w,math.ceil(x+bw)),min(h,math.ceil(y+bh))
    if x1-x0<3 or y1-y0<3:raise ValueError('Empty/tiny detector box')
    return x0,y0,x1,y1

def coherent_mask(mask,box,category):
    """Reject sparse/fragmented/leaking masks; remove only tiny disconnected islands.

    True openings remain untouched, including the sky inside an arch.
    Geometry cannot establish semantic correctness: the VLM audit remains required.
    """
    import numpy as np
    import torch
    from scipy import ndimage
    if mask.ndim!=2 or not torch.isfinite(mask).all():return None,'invalid mask'
    h,w=mask.shape;x0,y0,x1,y1=box_geometry(box,h,w)
    src=(mask.detach().cpu().numpy()>=.5)
    total=int(src.sum())
    if total<9:return None,'empty/tiny decoded selection'
    # Allow a small detector-box error without permitting an entire crop as foreground.
    pad=max(2,round(.02*max(x1-x0,y1-y0)))
    ax,ay,bx,by=max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad)
    inside=int(src[ay:by,ax:bx].sum())
    if inside/total<.8:return None,'decoder leaks substantially outside object box'
    selected=np.zeros_like(src);selected[ay:by,ax:bx]=src[ay:by,ax:bx]
    labels,count=ndimage.label(selected,np.ones((3,3),np.uint8))
    sizes=np.bincount(labels.ravel());sizes[0]=0
    largest=int(sizes.max());area=int(sizes.sum())
    if largest/max(1,area)<.45:return None,'fragmented selection: no dominant coherent component'
    thin=bool(re.search(r'\b(fence|railing|wire|branch|tree|vegetation)\b',category))
    fill=inside/max(1,(x1-x0)*(y1-y0))
    if fill < (.008 if thin else .07):return None,'outline/sparse selection instead of object surface'
    keep=np.flatnonzero(sizes>=max(3,math.ceil(largest*.003)))
    selected=np.isin(labels,keep)
    # No fill_holes/closing: preserve architectural openings and occlusions.
    return torch.from_numpy(selected),f'coherent decoder mask; box coverage {fill:.3f}; components {count}'

def decode_box(model,image,box):
    """One official box-only SAM pass on a contextual object crop.

    No text conditioning means the official node uses its SAM box decoder,
    not the text-detection path that ORs refined masks with coarse masks.
    """
    import torch
    from comfy_extras.nodes_sam3 import SAM3_Detect
    h,w=image.shape[1:3];x0,y0,x1,y1=box_geometry(box,h,w)
    pad=max(16,round(.12*max(x1-x0,y1-y0)))
    ax,ay,bx,by=max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad)
    local=dict(x=x0-ax,y=y0-ay,width=x1-x0,height=y1-y0,score=box['score'])
    out=SAM3_Detect.execute(model=model,image=image[:,ay:by,ax:bx,:3],bboxes=[local],
                           refine_iterations=1,individual_masks=True)
    masks=out[0].detach().float().cpu()
    if masks.ndim!=3 or masks.shape[0]!=1 or tuple(masks.shape[1:])!=(by-ay,bx-ax):
        raise ValueError('DOGMA: unexpected box decoder shape; update ComfyUI/SAM3.')
    result=torch.zeros((h,w));result[ay:by,ax:bx]=masks[0]
    return result

def get_state(notes):
    states=[json.loads(s[len(PREFIX):]) for s in notes if s.startswith(PREFIX)]
    return states[-1] if states else dict(attempts=0,pending=[],queries=[])

def uncovered_fraction(box,accepted,h,w):
    import torch
    x0,y0,x1,y1=box
    if x1<=x0 or y1<=y0:return 0.
    union=torch.zeros((y1-y0,x1-x0),dtype=torch.bool)
    for item in accepted:union |= item['mask'][y0:y1,x0:x1].cpu().bool()
    return 1.-float(union.float().mean())

class DOGMASAMCoherentSearchV109:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'model':('MODEL',),'clip':('CLIP',),
            'category':('STRING',{'forceInput':True}),'query_hint':('STRING',{'forceInput':True}),
            'mode':(['global','local_recovery'],),'threshold':('FLOAT',{'default':.25,'min':.05,'max':.9,'step':.01}),
            'max_instances':('INT',{'default':8,'min':2,'max':32}),
            'max_queries':('INT',{'default':3,'min':1,'max':4}),
            'recovery_views':('INT',{'default':2,'min':0,'max':4})},
            'optional':{'previous':('DOGMA_REVIEW',),'after':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('DOGMA_CANDIDATES','STRING');RETURN_NAMES=('candidates','search_report')
    FUNCTION='search';CATEGORY='DOGMA/v1.0.9'
    def search(self,image,model,clip,category,query_hint,mode,threshold,max_instances,max_queries=3,recovery_views=2,previous=None,after=None):
        import torch
        if image.ndim!=4 or image.shape[0]!=1:raise ValueError('DOGMA: one scene image required.')
        h,w=image.shape[1:3];category=old().canonical(category)
        if previous and (previous['category']!=category or tuple(previous['shape'])!=(h,w)):
            raise ValueError('DOGMA: recovery image/category mismatch.')
        if mode=='local_recovery' and previous is None:raise ValueError('DOGMA: missing previous audit.')
        notes=list(previous.get('notes',[])) if previous else []
        accepted=list(previous.get('accepted',[])) if previous else []
        state=get_state(notes);items=[];calls=0;decode_calls=0
        queries=query_list(category,query_hint,max_queries)
        reserve=min(int(recovery_views),int(max_instances)//2)
        remaining=max(0,int(max_instances)-state['attempts'])
        budget=min(remaining,max_instances-reserve) if mode=='global' else min(remaining,reserve)
        start=state['attempts'];pending=[]
        if mode=='global':
            jobs=[(q,(0,0,w,h)) for q in queries]
        else:
            # Retry rejected/missing object regions even when other objects passed.
            accepted_sources={i.get('source') for i in accepted}
            candidates=[p for p in state['pending'] if p.get('source') not in accepted_sources]
            candidates.sort(key=lambda p:-(p['priority']*uncovered_fraction(p['rect'],accepted,h,w)))
            jobs=[]
            for p in candidates:
                x0,y0,x1,y1=p['rect'];pad=max(32,round(.2*max(x1-x0,y1-y0)))
                rect=(max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad))
                if (p['query'],rect) not in jobs:jobs.append((p['query'],rect))
            # Specific queries not yet represented get a central contextual view first.
            represented={i.get('query') for i in accepted}
            for q in queries:
                if q not in represented:
                    jobs.append((q,(max(0,round(w*.1)),0,min(w,round(w*.9)),h)))
            if not jobs:
                windows=old().local_windows(h,w)
                windows.sort(key=lambda r:-uncovered_fraction(r,accepted,h,w))
                jobs=[(queries[0],r) for r in windows] if queries else []
            jobs=jobs[:int(recovery_views)]
        if not old().inactive(category):
            for ji,(query,(x0,y0,x1,y1)) in enumerate(jobs):
                capacity=budget-(state['attempts']-start)
                if capacity<=0:break
                quota=max(1,math.ceil(capacity/max(1,len(jobs)-ji)))
                raw,boxes=node('DOGMASAMSearchV567')._detect(model,clip,image[:,y0:y1,x0:x1,:3],query,threshold,min(16,quota*3))
                calls+=1
                boxlist=boxes[0] if isinstance(boxes,list) and len(boxes)==1 and isinstance(boxes[0],list) else boxes
                if raw.ndim==2:raw=raw[None]
                if not isinstance(boxlist,list) or len(raw)!=len(boxlist):raise ValueError('DOGMA: detector masks/boxes are not paired.')
                ranked=[]
                for box in boxlist:
                    try:
                        r=box_geometry(box,y1-y0,x1-x0)
                        priority=float(box['score'])*math.sqrt((r[2]-r[0])*(r[3]-r[1]))
                        if float(box['score'])>=threshold:ranked.append((priority,box,r))
                    except (ValueError,KeyError,OverflowError):continue
                ranked.sort(key=lambda x:-x[0])
                used=0
                for bi,(priority,box,r) in enumerate(ranked[:16]):
                    rect=(r[0]+x0,r[1]+y0,r[2]+x0,r[3]+y0)
                    source=f'{mode}/{ji+1}/{query}/{bi+1}'
                    record=dict(query=query,rect=rect,priority=priority,source=source)
                    pending.append(record)
                    if used>=quota:continue
                    # Already-owned near-complete boxes need no new decoder/audit call.
                    if uncovered_fraction(rect,accepted+items,h,w)<.1:continue
                    used+=1;state['attempts']+=1;decode_calls+=1
                    decoded=decode_box(model,image[:,y0:y1,x0:x1,:3],box)
                    mask,reason=coherent_mask(decoded,box,category)
                    if mask is None:
                        notes.append(f'{source}: RETRY/REJECT geometry: {reason}');continue
                    full=torch.zeros((h,w),dtype=torch.bool);full[y0:y1,x0:x1]=mask
                    item=dict(mask=full,score=float(box['score']),source=source,query=query)
                    items=support().bounded_instances(items+[item],accepted,max_instances)
                    notes.append(f'{source}: {reason}; box-only SAM decoder, no raw-mask union.')
        state['pending']=(state.get('pending',[])+pending)[-64:];state['queries']=queries
        notes=[n for n in notes if not n.startswith(PREFIX)]
        notes.append(PREFIX+json.dumps(state,separators=(',',':')))
        report=(f'{category} / {mode}: {calls} text detections, {decode_calls} one-pass object decodes, '
                f'{len(items)} candidates for strict audit; {len(accepted)} previously approved. '
                f'Total decoder-attempt budget {state["attempts"]}/{max_instances}; '
                f'{reserve} attempts reserved for recovery even after partial success. '
                'Bounded search, not guaranteed full coverage. Rejected/unsearched pixels remain unchanged.')
        notes.append(report)
        return dict(category=category,shape=(h,w),items=items,accepted=accepted,notes=notes),report

class DOGMAInstanceAuditViewV109:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'candidates':('DOGMA_CANDIDATES',),'panel_size':('INT',{'default':512,'min':256,'max':768,'step':64})}}
    RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('instance_sheets','audit_instructions')
    OUTPUT_IS_LIST=(True,True);FUNCTION='build';CATEGORY='DOGMA/v1.0.9'
    def build(self,image,candidates,panel_size=512):
        sheets,_=node('DOGMAInstanceAuditViewV567')().build(image,candidates,panel_size)
        prompts=[]
        for item in candidates['items']:
            prompts.append(f'Validate segmentation of "{candidates["category"]}", specifically "{item.get("query",candidates["category"])}". '
                'The 2x2 sheet shows the original crop, white foreground mask, cyan overlay, and selected pixels on gray. '
                'PASS only if the mask selects the substantial visible body of a coherent target object or structural unit. '
                'FAIL if it selects only outlines, highlights, isolated windows or scattered surface fragments while the main visible body is unselected. '
                'FAIL for background, sky, a crop-shaped rectangle, or unrelated classes selected as the target. '
                'An architectural arch means its solid masonry and piers; preserve the actual opening/sky and occlusions as unselected. '
                'Occluded parts and true openings need not be filled. Several visible components of the SAME occluded object are valid. '
                'Other separate objects can remain unselected. Respond PASS or FAIL followed by a short factual reason.')
        return sheets,prompts or ['No candidate; return FAIL.']

class DOGMAInstanceReviewV109:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'candidates':('DOGMA_CANDIDATES',),'audit_text':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('DOGMA_REVIEW','STRING');RETURN_NAMES=('review','audit_report')
    INPUT_IS_LIST=True;FUNCTION='review';CATEGORY='DOGMA/v1.0.9'
    def review(self,candidates,audit_text):
        result,_=node('DOGMAInstanceReviewV567')().review(candidates,audit_text)
        return result,'\n'.join(n for n in result['notes'] if not n.startswith(PREFIX))

class DOGMAFinalMasksV109:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'review':('DOGMA_REVIEW',)}}
    RETURN_TYPES=('MASK','STRING');RETURN_NAMES=('approved_instances','report')
    FUNCTION='finish';CATEGORY='DOGMA/v1.0.9'
    def finish(self,review):
        public=dict(review,notes=[n for n in review['notes'] if not n.startswith(PREFIX)])
        return node('DOGMAFinalMasksBoundedV2')().finish(public)

NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMASemanticPlanV109,DOGMASAMCoherentSearchV109,DOGMAInstanceAuditViewV109,DOGMAInstanceReviewV109,DOGMAFinalMasksV109)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V109',' v1.0.9') for k in NODE_CLASS_MAPPINGS}
