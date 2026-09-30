"""Larger two-candidate audit sheets; no automatic rejection for parse failures."""
import math,re,sys
BATCH=2
PREFIX="DOGMA110_STATE="
def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]

class DOGMAAuditBatchV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'candidates':('DOGMA_CANDIDATES',),'panel_size':('INT',{'default':512,'min':256,'max':768,'step':64})}}
    RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('instance_sheets','audit_instructions')
    OUTPUT_IS_LIST=(True,True);FUNCTION='build';CATEGORY='DOGMA/v1.0.11'
    def build(self,image,candidates,panel_size=512):
        import numpy as np
        import torch
        import torch.nn.functional as F
        from PIL import Image,ImageDraw,ImageFont
        if not candidates['items']:return [torch.zeros((1,64,64,3))],['No candidates.']
        sheets,_=node('DOGMAInstanceAuditViewV567')().build(image,candidates,panel_size)
        grids=[];prompts=[];side=768
        for offset in range(0,len(sheets),BATCH):
            chunk=sheets[offset:offset+BATCH];grid=torch.full((1,side*2,side,3),.12)
            for j,sheet in enumerate(chunk):
                h,w=sheet.shape[1:3];scale=min((side-40)/h,side/w)
                sh,sw=max(1,round(h*scale)),max(1,round(w*scale))
                tile=F.interpolate(sheet.movedim(-1,1),size=(sh,sw),mode='bilinear',align_corners=False).movedim(1,-1)
                y=j*side;x=0
                grid[:,y+40:y+40+sh,x+(side-sw)//2:x+(side-sw)//2+sw]=tile
                banner=Image.new('RGB',(side,36),(20,20,20));draw=ImageDraw.Draw(banner)
                try:font=ImageFont.load_default(size=22)
                except TypeError:font=ImageFont.load_default()
                draw.text((10,5),f'{j+1}: {candidates["category"]}',font=font,fill='white')
                grid[:,y:y+36,x:x+side]=torch.from_numpy(np.asarray(banner).copy()).float()/255
            grids.append(grid)
            prompts.append(f'Audit {len(chunk)} numbered candidates for {candidates["category"]}. '
                'Each numbered tile contains original crop, white mask, cyan overlay and selected pixels on gray. '
                'Judge selected pixels, not whether the target is somewhere in the original crop. PASS only selections whose substantial regions actually belong to the named category. Partial objects and real openings are allowed. '
                'FAIL substantial selection of unrelated objects, sky, architecture, ground or background; also FAIL an absent target. In a people mask, any substantial selected building or sky is a FAIL even if real people are also selected. '
                'Do not fail for missing other objects or incomplete coverage. '
                f'Return exactly {len(chunk)} lines in order: 1 PASS or 1 FAIL, then 2 PASS or 2 FAIL, and so on. Add a short reason after each verdict.')
        return grids,prompts

class DOGMAReviewBatchV111:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'candidates':('DOGMA_CANDIDATES',),'audit_text':('STRING',{'forceInput':True}),
        'audit_mode':(['report_only','reject_explicit_fail'],{'default':'reject_explicit_fail'})}}
    RETURN_TYPES=('DOGMA_REVIEW','STRING');RETURN_NAMES=('review','audit_report')
    INPUT_IS_LIST=True;FUNCTION='review';CATEGORY='DOGMA/v1.0.11'
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


NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMAAuditBatchV111,DOGMAReviewBatchV111)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V111',' v1.0.11') for k in NODE_CLASS_MAPPINGS}
