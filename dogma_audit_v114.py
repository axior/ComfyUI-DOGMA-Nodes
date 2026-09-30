"""Category-relative audit: ground/architecture are valid when they are the target."""
import math,re,sys
BATCH=2
PREFIX="DOGMA110_STATE="
def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]

def audit_prompt(category, count):
    target = ' '.join(str(category).split())[:100]
    lower = target.lower()
    guidance = ''
    if any(word in lower for word in ('road','pav','ground','asphalt','cobble','floor','soil','street')):
        guidance = ('This target is a continuous ground surface. Visible road, paving, sidewalk or plaza '
                    'can be valid where appropriate to the target. Darkness, wet reflections, paving joints '
                    'and shadows do not change the surface category. It need not be one bounded object. ')
    elif any(word in lower for word in ('building','architect','arch','facade','colonnade','cathedral')):
        guidance = ('Architecture is the target here. Walls, roofs, columns and facade components can '
                    'belong to it. Real openings, occlusion and partial structures are valid. ')
    return (f'Audit {count} numbered candidate masks. TARGET CATEGORY: {target}. '
            'Each numbered tile is a 2x2 sheet: top-left original crop; top-right white selected mask; '
            'bottom-left cyan overlay; bottom-right selected image pixels on gray. '
            'White/cyan indicate selection. Black in the mask and gray outside selected pixels are NOT selected. '
            'Judge the selected pixels against the target, not everything visible in the original crop. '
            + guidance +
            'PASS if the substantial selected regions belong to the target category. '
            'FAIL only if substantial selected regions clearly belong to a DIFFERENT category, '
            'or if no target is visible in the selection. Name the wrongly selected category in the reason. '
            'Never reject the target itself merely because it is ground, architecture, sky or background. '
            'Partial coverage, occlusion and real openings are allowed; missing other instances is not failure. '
            'Use REVIEW if the image or selection is too ambiguous to judge. '
            f'Return exactly {count} numbered lines in order, e.g. 1 PASS: short visual reason. '
            'Use PASS, FAIL or REVIEW, with a short reason for each. No other text.')


class DOGMAAuditBatchV114:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'candidates':('DOGMA_CANDIDATES',),'panel_size':('INT',{'default':512,'min':256,'max':768,'step':64})}}
    RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('instance_sheets','audit_instructions')
    OUTPUT_IS_LIST=(True,True);FUNCTION='build';CATEGORY='DOGMA/v1.0.14'
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
            prompts.append(audit_prompt(candidates['category'],len(chunk)))
        return grids,prompts

class DOGMAReviewBatchV114:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'candidates':('DOGMA_CANDIDATES',),'audit_text':('STRING',{'forceInput':True}),
        'audit_mode':(['report_only','reject_explicit_fail'],{'default':'reject_explicit_fail'})}}
    RETURN_TYPES=('DOGMA_REVIEW','STRING');RETURN_NAMES=('review','audit_report')
    INPUT_IS_LIST=True;FUNCTION='review';CATEGORY='DOGMA/v1.0.14'
    def review(self,candidates,audit_text,audit_mode):
        if len(candidates)!=1:raise ValueError('DOGMA: exactly one candidate bundle required.')
        data=candidates[0];items=data['items'];accepted=list(data['accepted']);lines=[]
        mode=audit_mode[0] if isinstance(audit_mode,list) else audit_mode
        if mode not in ('report_only','reject_explicit_fail'):raise ValueError('Unknown audit mode')
        if items and len(audit_text)!=math.ceil(len(items)/BATCH):raise ValueError('DOGMA: audit batch count mismatch.')
        for bi,text in enumerate(audit_text):
            votes={};ambiguous=set();reasons={}
            text=re.sub(r'<think>.*?</think>','',str(text)[:16000],flags=re.S|re.I)
            if '<think>' in text.lower():text=text[:text.lower().index('<think>')]
            for line in text.splitlines():
                match=re.match(r'^\s*(?:[-*]\s*)?(\d+)\s*[.):=-]?\s*(PASS|FAIL|REVIEW)\b(.*)',line,re.I)
                if match:
                    ident=int(match[1]);vote=match[2].upper()
                    if ident in votes and votes[ident]!=vote:ambiguous.add(ident)
                    votes[ident]=vote
                    reasons[ident]=' '.join(match[3].strip(' :-').split())[:350]
            for j,item in enumerate(items[bi*BATCH:(bi+1)*BATCH],1):
                vote='REVIEW' if j in ambiguous else votes.get(j,'REVIEW')
                keep=mode=='report_only' or vote!='FAIL'
                if keep:accepted.append(item)
                reason='contradictory verdicts; inspect mask' if j in ambiguous else reasons.get(j,'')
                reason=reason or 'no readable visual reason returned; inspect mask'
                lines.append(f'{item["source"]}: audit {vote}; {"KEPT" if keep else "REJECTED"}; mode={mode}; reason={reason}')
        notes=data['notes']+lines
        result=dict(category=data['category'],shape=data['shape'],accepted=accepted,notes=notes)
        return result,'\n'.join(s for s in notes if not s.startswith(PREFIX))


NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMAAuditBatchV114,DOGMAReviewBatchV114)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V114',' v1.0.14') for k in NODE_CLASS_MAPPINGS}
