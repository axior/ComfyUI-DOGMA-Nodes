"""DOGMA 1.0.11: live sampler catalogue, grounded eight-category plans,
interactive category selection and lazy phase/slot controls.
"""
import asyncio, json, re, secrets, sys, threading, time

def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]

def module(name):return sys.modules[node(name).__module__]

def sampler_catalogue():
    import comfy.samplers
    import nodes
    names=list(dict.fromkeys(list(comfy.samplers.SAMPLER_NAMES)+list(comfy.samplers.KSampler.SAMPLERS)))
    dogma=nodes.NODE_CLASS_MAPPINGS.get('DOGMASamplerSelect')
    if dogma:
        names+=['DOGMA / '+n for n in dogma.INPUT_TYPES()['required']['sampler_name'][0]]
    clown=nodes.NODE_CLASS_MAPPINGS.get('ClownSampler_Beta')
    if clown:
        mod=sys.modules[clown.__module__]
        names+=['RES4LYF / '+n for n in mod.get_sampler_name_list()]
    return list(dict.fromkeys(names))

class DOGMAAllSamplerSelectV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{
        'sampler_name':(sampler_catalogue(),{'default':'euler'}),
        'res_eta':('FLOAT',{'default':.3,'min':-100.,'max':100.,'step':.01}),
        'res_bongmath':('BOOLEAN',{'default':True}),
        'seed':('INT',{'default':1976,'min':0,'max':0xffffffffffffffff})}}
    RETURN_TYPES=('SAMPLER',);RETURN_NAMES=('sampler',);FUNCTION='select';CATEGORY='DOGMA/v1.0.11'
    def select(self,sampler_name,res_eta=.3,res_bongmath=True,seed=1976):
        import comfy.samplers
        import nodes
        if sampler_name not in sampler_catalogue():raise ValueError('Sampler no longer installed: '+sampler_name)
        if sampler_name.startswith('RES4LYF / '):
            return (node('ClownSampler_Beta').execute(sampler_name=sampler_name.split(' / ',1)[1],eta=res_eta,bongmath=res_bongmath,seed=seed)[0],)
        dogma=nodes.NODE_CLASS_MAPPINGS.get('DOGMASamplerSelect')
        name=sampler_name.split(' / ',1)[1] if sampler_name.startswith('DOGMA / ') else sampler_name
        if dogma and name in dogma.INPUT_TYPES()['required']['sampler_name'][0]:return dogma().get_sampler(name)
        return (comfy.samplers.sampler_object(name),)

def parse_json(text):
    text=re.sub(r'<think>.*?</think>','',str(text),flags=re.S|re.I).strip()
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I)
    start=text.find('[');end=text.rfind(']')
    if start<0 or end<start:raise ValueError('DOGMA: inventory must be a JSON array; inspect the raw planner output.')
    result=json.loads(text[start:end+1])
    if not isinstance(result,list):raise ValueError('DOGMA: expected an inventory array.')
    return result

def clean_phrase(text):return ' '.join(re.sub(r'[^a-zA-Z0-9 -]',' ',str(text)).lower().split()[:6])

def target_queries(category,queries):
    # Text SAM needs object nouns, not scene names, proper names or vague groups.
    fixed={'people':['person','pedestrian'],'road':['road surface','paved ground'],
           'vegetation':['tree','shrub'],'sky':['sky']}
    if category in fixed:return fixed[category]
    banned={'group','crowd','scene','foreground','background','city','urban','street scene','italy','italian','porta nuova'}
    keep=[q for q in queries if q not in banned and not any(x in q for x in ('1970','cinematic','shot on'))]
    return list(dict.fromkeys(keep or [category]))[:3]

class DOGMAProposeCategoriesV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'planner_text':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('DOGMA_PLAN','STRING','STRING');RETURN_NAMES=('proposal','presence_prompt','report')
    FUNCTION='build';CATEGORY='DOGMA/v1.0.11'
    def build(self,planner_text):
        old=module('DOGMASAMSearchV567');items=[];seen=set()
        for row in parse_json(planner_text):
            if not isinstance(row,dict):continue
            category=old.canonical(clean_phrase(row.get('category','')))
            evidence=str(row.get('evidence','')).strip()[:350]
            if old.inactive(category) or category in seen or not evidence:continue
            queries=row.get('queries',[])
            if not isinstance(queries,list):queries=[]
            queries=list(dict.fromkeys([clean_phrase(q) for q in queries if clean_phrase(q)]))[:3]
            items.append(dict(category=category,evidence=evidence,queries=target_queries(category,queries)));seen.add(category)
            if len(items)==8:break
        proposal=[dict(id=i+1,**item) for i,item in enumerate(items)]
        # Do not supply the first model's evidence to the independent visual check.
        targets=[{'id':p['id'],'category':p['category']} for p in proposal]
        prompt=('Check the actual photograph independently. For each proposed category below decide whether at least one object or surface of that category is visibly present. '
            'Do not assume a proposal is correct. Do not infer objects from setting, era, prompts or expected scene contents. '
            'Return a JSON array of objects with id, verdict (present, absent or uncertain), and a brief visible evidence/location. '
            'Use absent when the category is not visible and uncertain when too small or ambiguous. Proposals: '+json.dumps(targets))
        return proposal,prompt,json.dumps(proposal,ensure_ascii=False,indent=2)

class DOGMAVerifiedPlan8V111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'proposal':('DOGMA_PLAN',),'presence_text':('STRING',{'forceInput':True}),
        'sam_threshold':('FLOAT',{'default':.4,'min':.05,'max':.9,'step':.01})}}
    RETURN_TYPES=('STRING',)+('STRING','STRING','FLOAT')*8
    RETURN_NAMES=('plan_preview',)+tuple(x for i in range(1,9) for x in (f'category_{i}',f'sam_prompt_{i}',f'sam_threshold_{i}'))
    FUNCTION='build';CATEGORY='DOGMA/v1.0.11'
    def build(self,proposal,presence_text,sam_threshold=.4):
        votes={};duplicates=set()
        for row in parse_json(presence_text):
            if not isinstance(row,dict):continue
            ident=row.get('id')
            if type(ident) is not int:continue
            if ident in votes:duplicates.add(ident)
            votes[ident]=row
        accepted=[];lines=[]
        for p in proposal:
            v=votes.get(p['id'],{});verdict=str(v.get('verdict','uncertain')).strip().lower()
            evidence=str(v.get('evidence','')).strip()
            confirmed=verdict=='present' and bool(evidence) and p['id'] not in duplicates
            lines.append(f'{p["category"]}: {"CONFIRMED" if confirmed else "SKIPPED"} ({verdict}) — {evidence or "no unambiguous visual evidence"}')
            if confirmed:accepted.append(p)
        outputs=[]
        for p in accepted+[None]*(8-len(accepted)):
            outputs.extend((p['category'],'; '.join(p['queries']),sam_threshold) if p else ('none','',sam_threshold))
        return ('VISUAL PRESENCE CHECK (can still be wrong; inspect the masks):\n'+'\n'.join(lines),*outputs)

class DOGMAPresenceTextV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'proposal':('DOGMA_PLAN',),'text':('STRING',{'forceInput':True,'lazy':True})}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('presence_text',);FUNCTION='choose';CATEGORY='DOGMA/v1.0.11'
    def check_lazy_status(self,proposal,text=None):return ['text'] if proposal and text is None else []
    def choose(self,proposal,text=None):return (text if proposal else '[]',)

class DOGMASAMCoverageLazyV111:
    @classmethod
    def INPUT_TYPES(cls):
        import copy
        inputs=copy.deepcopy(node('DOGMASAMCoverageV110').INPUT_TYPES())
        for name in ('model','clip'):inputs['required'][name]=(inputs['required'][name][0],{'lazy':True})
        inputs['required']['refine_iterations'][1]['default']=0
        return inputs
    RETURN_TYPES=('DOGMA_CANDIDATES','STRING');RETURN_NAMES=('candidates','search_report')
    FUNCTION='search';CATEGORY='DOGMA/v1.0.11'
    def check_lazy_status(self,category,model=None,clip=None,**kwargs):
        if module('DOGMASAMSearchV567').inactive(category):return []
        return [k for k,v in [('model',model),('clip',clip)] if v is None]
    def search(self,model=None,clip=None,**kwargs):
        return node('DOGMASAMCoverageV110')().search(model=model,clip=clip,**kwargs)

class DOGMAFinalCleanMasksV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'review':('DOGMA_REVIEW',),'clean_micro_holes':('BOOLEAN',{'default':True})}}
    RETURN_TYPES=('MASK','STRING');RETURN_NAMES=('approved_instances','report');FUNCTION='finish';CATEGORY='DOGMA/v1.0.11'
    def finish(self,review,clean_micro_holes=True):
        import torch
        from scipy import ndimage
        masks,report=node('DOGMAFinalCoverageV110')().finish(review)
        changed=0
        if clean_micro_holes:
            # Repair only enclosed defects <=4 analysis pixels, with a strict per-instance
            # 0.5% area budget. Never close/dilate silhouettes, remove small subjects or fill arches.
            for i in range(len(masks)):
                src=masks[i].numpy()>=.5
                holes=ndimage.binary_fill_holes(src)&~src
                labels,count=ndimage.label(holes)
                if not count:continue
                import numpy as np
                sizes=np.bincount(labels.ravel());ids=np.flatnonzero((sizes>0)&(sizes<=4));ids=ids[ids!=0]
                fix=np.isin(labels,ids);n=int(fix.sum())
                if n<=int(src.sum()*.005):masks[i]=torch.from_numpy(src|fix).float();changed+=n
        return masks,report+f'\nMicro-hole repair: {changed} pixels; no silhouette dilation, no object deletion, holes larger than 4 analysis pixels preserved.'

class DOGMACategories8V111:
    @classmethod
    def INPUT_TYPES(cls):
        req={'image':('IMAGE',)}
        for i in range(1,9):req.update({f'mask_{i}':('MASK',),f'category_{i}':('STRING',{'forceInput':True})})
        return {'required':req}
    RETURN_TYPES=('DOGMA_CATEGORIES','IMAGE','STRING');RETURN_NAMES=('categories','category_previews','category_names')
    FUNCTION='build';CATEGORY='DOGMA/v1.0.11'
    def build(self,image,**kwargs):
        import torch
        import torch.nn.functional as F
        from PIL import Image,ImageDraw,ImageFont
        import numpy as np
        h,w=image.shape[1:3];rh=max(1,round(h*min(1,768/max(h,w))));rw=max(1,round(w*min(1,768/max(h,w))))
        base=F.interpolate(image[:1,...,:3].detach().float().cpu().movedim(-1,1),size=(rh,rw),mode='bilinear',align_corners=False).movedim(1,-1)
        entries=[];cards=[]
        for i in range(1,9):
            masks=kwargs[f'mask_{i}'].detach().float().cpu();name=kwargs[f'category_{i}']
            active=not module('DOGMASAMSearchV567').inactive(name) and masks.numel()>0 and bool((masks>=.5).any())
            entries.append(dict(slot=i,name=name,masks=masks,active=active))
            if not active:continue
            union=masks.max(0).values[None,None]
            small=F.interpolate(union,size=(rh,rw),mode='nearest').movedim(1,-1)>=.5
            cyan=torch.tensor([0.,.85,1.]).view(1,1,1,3)
            overlay=torch.where(small,base*.55+cyan*.45,base*.6)
            # Three views: original / mask / overlay. Keep semantic IDs independent of image order.
            content=torch.cat([base,small.float().expand(-1,-1,-1,3),overlay],2)
            banner=Image.new('RGB',(rw*3,48),(25,25,25));draw=ImageDraw.Draw(banner)
            try:font=ImageFont.load_default(size=24)
            except TypeError:font=ImageFont.load_default()
            draw.text((12,10),f'{i}. {name}  |  original / mask / overlay',fill='white',font=font)
            title=torch.from_numpy(np.asarray(banner).copy()).float()[None]/255
            cards.append(torch.cat([title,content],1))
        batch=torch.cat(cards,0) if cards else torch.zeros((1,64,192,3))
        bundle={'entries':entries,'shape':(h,w),'image':image}
        return bundle,batch,'\n'.join(f'{e["slot"]}. {e["name"]}: {"available" if e["active"] else "inactive / empty"}' for e in entries)

PENDING={}
LOCK=threading.Lock()

def submit_selection(token,indices):
    with LOCK:
        entry=PENDING.get(token)
        if entry is None:return False,'Selection expired or already completed.'
        if entry.get('selected') is not None:return False,'Selection already submitted.'
        if not isinstance(indices,list) or any(type(i) is not int for i in indices):return False,'Expected integer category IDs.'
        if len(set(indices))!=len(indices) or not set(indices)<=set(entry['allowed']):return False,'Invalid category IDs.'
        entry['selected']=indices
        return True,'OK'

def register_routes():
    from server import PromptServer
    from aiohttp import web
    @PromptServer.instance.routes.post('/dogma/categories/select')
    async def select(request):
        try:
            data=await request.json();ok,message=submit_selection(data.get('token'),data.get('indices'))
            return web.json_response({'ok':ok,'message':message},status=200 if ok else 400)
        except (ValueError,TypeError):return web.json_response({'ok':False,'message':'Invalid request'},status=400)
    @PromptServer.instance.routes.get('/dogma/categories/pending')
    async def pending(request):
        # Same authenticated ComfyUI origin. Tokens identify one waiting execution only.
        with LOCK:items=[e['payload'] for e in PENDING.values() if e.get('selected') is None]
        return web.json_response({'items':items})

class DOGMAChooseCategoriesV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'categories':('DOGMA_CATEGORIES',),'previews':('IMAGE',),
        'manual':('BOOLEAN',{'default':False})},'hidden':{'unique_id':'UNIQUE_ID'}}
    RETURN_TYPES=('DOGMA_CATEGORIES','STRING');RETURN_NAMES=('selected_categories','selection_report')
    FUNCTION='choose';CATEGORY='DOGMA/v1.0.11'
    @classmethod
    def IS_CHANGED(cls,manual,**kwargs):return float('nan') if manual else False
    async def choose(self,categories,previews,manual,unique_id=None):
        available=[e for e in categories['entries'] if e['active']]
        selected=[e['slot'] for e in available]
        if manual and available:
            import nodes
            from server import PromptServer
            import comfy.model_management
            saved=nodes.PreviewImage().save_images(previews)['ui']['images']
            token=secrets.token_urlsafe(24)
            payload={'token':token,'node_id':str(unique_id),'categories':[{'id':e['slot'],'name':e['name'],'image':url} for e,url in zip(available,saved)]}
            entry={'allowed':selected,'selected':None,'payload':payload}
            with LOCK:PENDING[token]=entry
            try:
                PromptServer.instance.send_sync('dogma-category-choice',payload)
                while True:
                    comfy.model_management.throw_exception_if_processing_interrupted()
                    with LOCK:selection=entry['selected']
                    if selection is not None:selected=selection;break
                    await asyncio.sleep(.2)
            finally:
                with LOCK:PENDING.pop(token,None)
                PromptServer.instance.send_sync('dogma-category-choice-close',{'token':token})
        result=dict(categories,selected=selected)
        report=('MANUAL' if manual else 'AUTO')+': '+(', '.join(e['name'] for e in available if e['slot'] in selected) or 'no categories selected; phase 3 passes the input image through')
        return result,report

class DOGMASelectedMasks8V111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'selection':('DOGMA_CATEGORIES',)}}
    RETURN_TYPES=('MASK',)*8+('BOOLEAN',)*8+('STRING',)
    RETURN_NAMES=tuple(f'mask_{i}' for i in range(1,9))+tuple(f'enabled_{i}' for i in range(1,9))+('ownership_report',)
    FUNCTION='unpack';CATEGORY='DOGMA/v1.0.11'
    def unpack(self,selection):
        import torch
        entries=selection['entries'];chosen=set(selection['selected']);old=module('DOGMASAMSearchV567')
        shape=entries[0]['masks'].shape[-2:];occupied=torch.zeros(shape,dtype=torch.bool);out=[None]*8;flags=[False]*8;report=[]
        def priority(e):
            c=old.canonical(e['name'])
            return 0 if c=='people' else 1 if c=='vehicles' else 3 if old.structural(c) else 4 if c in {'road','ground','pavement','floor','water','grass','vegetation','sky'} else 2
        for e in sorted(entries,key=priority):
            idx=e['slot']-1;m=e['masks'].bool()
            if e['slot'] not in chosen:m=m[:0]
            else:
                if m.shape[-2:]!=shape:raise ValueError('Category mask resolutions differ.')
                m=m&~occupied
                if m.numel():m=m[m.flatten(1).any(1)]
                if len(m):occupied|=m.any(0)
            out[idx]=m.float();flags[idx]=bool(m.numel() and m.any())
            report.append(f'{e["slot"]}. {e["name"]}: {"render" if flags[idx] else "skip"}; {len(m)} masks')
        return (*out,*flags,'\n'.join(report))

class DOGMAScaleFactorV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'original':('IMAGE',)}}
    RETURN_TYPES=('FLOAT',);RETURN_NAMES=('factor',);FUNCTION='size';CATEGORY='DOGMA/v1.0.11'
    def size(self,image,original):return (image.shape[2]/original.shape[2],)

class DOGMAResolutionKV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'resolution_k':('INT',{'default':5,'min':1,'max':8})}}
    RETURN_TYPES=('INT',);RETURN_NAMES=('long_side',);FUNCTION='size';CATEGORY='DOGMA/v1.0.11'
    def size(self,resolution_k):return (max(1,min(8,resolution_k))*1024,)

NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMAAllSamplerSelectV111,DOGMAProposeCategoriesV111,DOGMAVerifiedPlan8V111,DOGMAPresenceTextV111,DOGMASAMCoverageLazyV111,DOGMACategories8V111,DOGMAChooseCategoriesV111,DOGMASelectedMasks8V111,DOGMAScaleFactorV111,DOGMAResolutionKV111,DOGMAFinalCleanMasksV111)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V111',' v1.0.11') for k in NODE_CLASS_MAPPINGS}
