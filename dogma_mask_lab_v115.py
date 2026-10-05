"""Opt-in mask laboratory. Five sequential methods, one inventory, no diffusion.

Uses the installed Comfy SAM3 detector feature API, without monkey patches or
persistent GPU caches. Internal API compatibility is checked before inference.
"""
import copy
import csv
import json
import math
import re
import sys
import time
from pathlib import Path

METHODS = ('A raw text', 'B presence + geometry', 'C two-prompt agreement',
           'D box + point decoder', 'E four overlapping views')
ALIASES = {
    'buildings': ('building', 'architecture'),
    'road': ('paved ground', 'road surface'),
    'vehicles': ('vehicle', 'car'),
    'people': ('person', 'pedestrian'),
    'vegetation': ('tree', 'vegetation'),
    'lamp': ('street lamp', 'lamp post'),
    'sky': ('sky', 'open sky'),
    'water': ('water', 'water surface'),
    'floor': ('floor', 'floor surface'),
}
SYNONYMS = {'paved ground': 'road', 'pavement': 'road', 'asphalt': 'road',
            'street': 'road', 'stone paving': 'road', 'building': 'buildings',
            'architecture': 'buildings', 'person': 'people', 'pedestrians': 'people',
            'car': 'vehicles', 'cars': 'vehicles', 'vehicle': 'vehicles',
            'tree': 'vegetation', 'trees': 'vegetation', 'lamps': 'lamp',
            'street lamps': 'lamp', 'street lamp': 'lamp'}
PLAN_PROMPT = '''Inspect the actual photograph. List up to eight distinct VISIBLE category types.
Inspect ground and large surfaces first, then architecture and whole objects.
Do not omit visible pavement just because it is dark. Do not infer people or vehicles.
Avoid duplicates, object parts and categories such as light, reflections, shadows or image quality.
One line per category, not per instance: category | short concrete segmentation noun | visible location.
Use English. Only visible categories, no quota, no JSON or explanation. NONE if nothing is identifiable.'''


def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]


def interrupted():
    from comfy.model_management import throw_exception_if_processing_interrupted
    throw_exception_if_processing_interrupted()


def sync():
    import torch
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def resize_image(image, side):
    import torch.nn.functional as F
    if image.ndim != 4 or image.shape[0] != 1:
        raise ValueError('DOGMA lab: load one image, not a batch.')
    h, w = image.shape[1:3]
    scale = min(1., float(side) / max(h, w))
    size = (max(1, round(h * scale)), max(1, round(w * scale)))
    return F.interpolate(image[..., :3].movedim(-1, 1), size=size,
                         mode='bilinear', align_corners=False).movedim(1, -1).cpu()


def parse_inventory(text):
    legacy = sys.modules[node('DOGMAProposeCategoriesV112').__module__]
    rows, warnings = legacy.read_rows(text)
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        cat = ' '.join(re.sub('[^a-zA-Z -]', ' ', str(row.get('category', ''))).lower().split())
        cat = SYNONYMS.get(cat, cat)
        if not cat or cat in seen or cat in ('none', 'light', 'shadow', 'reflection', 'background'):
            continue
        if len(cat) > 60:
            continue
        supplied = row.get('queries', [])
        supplied = [str(q).strip()[:70] for q in supplied if isinstance(q, str)] if isinstance(supplied, list) else []
        primary, secondary = ALIASES.get(cat, (cat, cat))
        if supplied:
            custom = [q.strip() for q in supplied[0].split(';') if q.strip()]
            if custom:
                primary = custom[0]
                secondary = custom[1] if len(custom)>1 else secondary
        result.append(dict(category=cat, primary=primary, secondary=secondary,
                           evidence=str(row.get('evidence', 'manual proposal'))[:160]))
        seen.add(cat)
        if len(result) == 8:
            break
    return result, warnings


class DOGMAMaskLabPlanV115:
    @classmethod
    def INPUT_TYPES(cls):
        schema = copy.deepcopy(node('ModernVLM').INPUT_TYPES())
        required = {k: v for k, v in schema['required'].items()
                    if k in ('model', 'custom_model_id', 'memory_mode')}
        required.update(image=('IMAGE',), mode=(['auto_once', 'manual'],),
                        manual_categories=('STRING', {'multiline': True, 'default':
                            'road | paved ground | manual target\nbuildings | building | manual target\nvehicles | vehicle | manual target\npeople | person | manual target\nlamp | street lamp | manual target'}),
                        planner_side=('INT', {'default': 1024, 'min': 512, 'max': 1536, 'step': 128}),
                        rerun=('INT', {'default': 0, 'min': 0, 'max': 999999}))
        return {'required': required}
    RETURN_TYPES = ('DOGMA_LAB_PLAN', 'STRING')
    RETURN_NAMES = ('plan', 'inventory_and_time')
    FUNCTION = 'run'
    CATEGORY = 'DOGMA/Mask lab 1.0.15'

    def run(self, image, mode, manual_categories, planner_side, rerun,
            model, custom_model_id, memory_mode):
        start = time.perf_counter()
        interrupted()
        if mode == 'manual':
            raw = manual_categories
        else:
            worker = node('ModernVLM')()
            try:
                raw = worker.run(image=resize_image(image, planner_side), prompt=PLAN_PROMPT,
                                 model=model, custom_model_id=custom_model_id, memory_mode=memory_mode,
                                 max_new_tokens=224, temperature=0., top_p=.9,
                                 enable_thinking=False, unload_after=False, stream_output=True,
                                 system_prompt='Return distinct visible categories once each in the requested short line format.')[0]
            finally:
                worker.clear_model()
        items, warnings = parse_inventory(raw)
        elapsed = time.perf_counter() - start
        plan = dict(items=items, seconds=elapsed, raw=raw, warnings=warnings, mode=mode)
        report = (f'{mode}: {len(items)} categories; {elapsed:.2f}s including planner loading/cleanup. '
                  'One call, max224 tokens, no per-mask VLM audits. Categories are proposals, not verified truth.\n'
                  + '\n'.join(f'{i+1}. {r["category"]}: {r["primary"]} / {r["secondary"]}' for i, r in enumerate(items))
                  + '\nWarnings: ' + '; '.join(warnings) + '\nRAW:\n' + raw)
        return plan, report


def box_pixels(box, h, w):
    x0, y0, x1, y1 = [float(v) for v in box]
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        return None
    x0, y0 = max(0, math.floor(x0)), max(0, math.floor(y0))
    x1, y1 = min(w, math.ceil(x1)), min(h, math.ceil(y1))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def geometric_check(mask, box, max_coverage, min_box_agreement):
    area = int(mask.sum())
    if area < 4:
        return False, 'empty/tiny'
    h, w = mask.shape
    if area / (h * w) >= max_coverage:
        return False, 'near-full-view mask (heuristic, can reject a legitimate surface)'
    rect = box_pixels(box, h, w)
    if rect is None:
        return False, 'invalid detection box'
    x0, y0, x1, y1 = rect
    pad = max(2, round(.03 * max(x1-x0, y1-y0)))
    inside = int(mask[max(0,y0-pad):min(h,y1+pad), max(0,x0-pad):min(w,x1+pad)].sum())
    if inside / area < min_box_agreement:
        return False, 'mask extends substantially beyond its detection box'
    return True, 'geometry consistent; semantic correctness unverified'


def union(items, h, w):
    import torch
    out = torch.zeros((h, w), dtype=torch.bool)
    for item in items:
        out |= item['mask']
    return out


def agreement(left, right, minimum=.35):
    import torch
    result = []
    for a in left:
        partners = []
        for b in right:
            overlap = int((a['mask'] & b['mask']).sum())
            total = int((a['mask'] | b['mask']).sum())
            if overlap / max(1, total) >= minimum:
                partners.append(b['mask'])
        if partners:
            mask = a['mask'] & torch.stack(partners).any(0)
            if int(mask.sum()) >= 4:
                result.append(dict(a, mask=mask))
    return result


class SAMSession:
    """Feature reuse inside one view; state never survives a method execution."""
    def __init__(self, model, encodings):
        import comfy.model_management as mm
        mm.load_model_gpu(model)
        self.sam = model.model.diffusion_model
        self.det = getattr(self.sam, 'detector', None)
        if self.det is None or not all(callable(getattr(self.det, x, None)) for x in ('_get_backbone_features', '_detect')):
            raise RuntimeError('DOGMA lab requires the ComfyUI core SAM3 detector feature API. Update ComfyUI core; no silent slow fallback.')
        self.device = mm.get_torch_device()
        self.dtype = model.model.get_dtype()
        self.encodings = encodings
        self.backbones = 0
        self.detections = 0
        self.refinements = 0

    def prepare(self, image):
        import comfy.utils
        interrupted()
        self.clear()
        self.h, self.w = image.shape[1:3]
        self.frame = comfy.utils.common_upscale(image.movedim(-1,1), 1008, 1008, 'bilinear', crop='disabled').to(self.device, self.dtype)
        self.features, self.positions, _, _ = self.det._get_backbone_features(self.frame)
        self.backbones += 1

    def detect(self, query, threshold, limit, use_presence):
        import torch
        import torch.nn.functional as F
        interrupted()
        emb, textmask = self.encodings[query]
        emb = self.det.backbone['language_backbone']['resizer'](emb.to(self.device, self.dtype))
        textmask = textmask.to(self.device).bool() if textmask is not None else None
        boxes, scores, logits, dec = self.det._detect(self.features, self.positions, emb, textmask)
        self.detections += 1
        probs = scores[0].sigmoid().reshape(-1)
        if use_presence:
            presence = dec.get('presence')
            if presence is None or presence.numel() != 1:
                raise RuntimeError('SAM detector does not expose the expected per-image presence logit.')
            probs = probs * presence.sigmoid().reshape(())
        order = torch.where(torch.isfinite(probs) & (probs > threshold))[0]
        order = order[probs[order].argsort(descending=True)[:limit]]
        result = []
        if len(order):
            masks = F.interpolate(logits[0,order,None].float(), size=(self.h,self.w), mode='bilinear', align_corners=False)[:,0] > 0
            scaled = boxes[0,order] * torch.tensor([self.w,self.h,self.w,self.h], device=boxes.device)
            for j, ix in enumerate(order):
                if not torch.isfinite(logits[0,ix]).all():
                    continue
                result.append(dict(mask=masks[j].cpu(), box=scaled[j].cpu().tolist(), score=float(probs[ix])))
        return result

    def refine(self, item):
        import numpy as np
        import torch
        import torch.nn.functional as F
        from scipy.ndimage import distance_transform_edt
        interrupted()
        rect = box_pixels(item['box'],self.h,self.w)
        if rect is None:
            return None
        x0,y0,x1,y1 = rect
        arr = item['mask'].numpy()
        local = arr[y0:y1,x0:x1]
        if not local.any():
            return None
        distance = distance_transform_edt(np.pad(local,1))[1:-1,1:-1]
        y,x = np.unravel_index(distance.argmax(),distance.shape)
        point = [(x+x0+.5)/self.w*1008,(y+y0+.5)/self.h*1008]
        points = dict(point_coords=torch.tensor([[point]],device=self.device,dtype=self.dtype),
                      point_labels=torch.ones((1,1),device=self.device,dtype=torch.int32))
        box = torch.tensor([[[x0/self.w*1008,y0/self.h*1008],
                             [x1/self.w*1008,y1/self.h*1008]]],device=self.device,dtype=self.dtype)
        # One standard core decoder call per selected instance, never OR with coarse mask.
        logits = self.sam.forward_segment(self.frame, point_inputs=points, box_inputs=box)
        self.backbones += 1
        self.refinements += 1
        if not torch.isfinite(logits).all():
            return None
        mask = F.interpolate(logits.float(),size=(self.h,self.w),mode='bilinear',align_corners=False)[0,0] > 0
        return dict(item,mask=mask.cpu())

    def clear(self):
        self.features = None
        self.positions = None
        self.frame = None


def execute_method(session, image, rows, method, threshold, cap, max_coverage,
                   min_box_agreement, refinement_budget, overlap):
    import torch
    h,w = image.shape[1:3]
    entries = [dict(category=r['category'], mask=torch.zeros((h,w),dtype=torch.bool),
                    rejected=torch.zeros((h,w),dtype=torch.bool), notes=[], detected=0, kept=0) for r in rows]
    def filter_items(items, entry):
        accepted = []
        for item in items:
            ok, reason = geometric_check(item['mask'],item['box'],max_coverage,min_box_agreement)
            if ok:
                accepted.append(item)
            else:
                entry['notes'].append(reason)
        return accepted
    if method != 'E':
        session.prepare(image)
        remaining = refinement_budget
        for category_index,(row,e) in enumerate(zip(rows,entries)):
            initial = session.detect(row['primary'],threshold,cap,method!='A')
            e['detected'] = len(initial)
            valid = initial if method=='A' else filter_items(initial,e)
            if method=='C':
                if row['secondary'] == row['primary']:
                    e['notes'].append('NO DISTINCT SECOND PROMPT: empty consensus, edit category aliases before drawing conclusions')
                    valid = []
                else:
                    second = filter_items(session.detect(row['secondary'],threshold,cap,True),e)
                    e['detected'] += len(second)
                    valid = agreement(valid,second)
                    e['notes'].append('Intersection of masks with IoU >=0.35; can lose valid targets when synonyms disagree')
            elif method=='D':
                refined = []
                allowance = math.ceil(remaining / max(1,len(rows)-category_index))
                for item in valid:
                    if remaining <= 0 or allowance <= 0:
                        refined.append(item)
                        e['notes'].append('Per-category/scene refinement cap reached: retained guarded coarse candidate')
                        continue
                    remaining -= 1
                    allowance -= 1
                    result = session.refine(item)
                    if result is not None:
                        refined.extend(filter_items([result],e))
                    else:
                        e['notes'].append('Decoder produced no valid mask; candidate omitted')
                valid = refined
            e['kept'] = len(valid)
            e['mask'] = union(valid,h,w)
            e['rejected'] = union(initial,h,w) & ~e['mask']
            if method=='A' and e['mask'].float().mean() >= max_coverage:
                e['notes'].append('WARNING near-full-view raw result, deliberately retained as baseline')
    else:
        # Partition cores plus overlap. Only each core owns its final pixels.
        # This avoids OR-ing every overlapping tile into a growing global mask.
        mx,my = w//2,h//2
        px,py = round(w*overlap/2),round(h*overlap/2)
        cores = [(0,0,mx,my),(mx,0,w,my),(0,my,mx,h),(mx,my,w,h)]
        for cx0,cy0,cx1,cy1 in cores:
            x0,y0,x1,y1 = max(0,cx0-px),max(0,cy0-py),min(w,cx1+px),min(h,cy1+py)
            session.prepare(image[:,y0:y1,x0:x1])
            for row,e in zip(rows,entries):
                initial = session.detect(row['primary'],threshold,cap,True)
                valid = filter_items(initial,e)
                e['detected'] += len(initial)
                e['kept'] += len(valid)
                accepted = union(valid,y1-y0,x1-x0)
                rejected = union(initial,y1-y0,x1-x0) & ~accepted
                sl = (slice(cy0-y0,cy1-y0),slice(cx0-x0,cx1-x0))
                e['mask'][cy0:cy1,cx0:cx1] = accepted[sl]
                e['rejected'][cy0:cy1,cx0:cx1] = rejected[sl]
        for e in entries:
            e['notes'].append('Four overlapping views, disjoint core ownership; possible seams; detections count includes repeated objects across views')
    return entries


class DOGMAMaskLabRunV115:
    @classmethod
    def INPUT_TYPES(cls):
        req = dict(image=('IMAGE',), plan=('DOGMA_LAB_PLAN',),
                   model=('MODEL',{'lazy':True}), clip=('CLIP',{'lazy':True}),
                   analysis_side=('INT',{'default':1536,'min':768,'max':2560,'step':128}),
                   score_threshold=('FLOAT',{'default':.35,'min':.05,'max':.95,'step':.01}),
                   max_instances=('INT',{'default':12,'min':1,'max':32}),
                   max_mask_coverage=('FLOAT',{'default':.97,'min':.5,'max':1.,'step':.01}),
                   min_box_agreement=('FLOAT',{'default':.85,'min':0.,'max':1.,'step':.05}),
                   refinement_budget=('INT',{'default':8,'min':0,'max':24}),
                   tile_overlap=('FLOAT',{'default':.2,'min':.05,'max':.4,'step':.05}),
                   reverse_order=('BOOLEAN',{'default':False}),
                   rerun=('INT',{'default':0,'min':0,'max':999999}))
        for method in 'ABCDE':
            req['run_'+method] = ('BOOLEAN',{'default':True})
        return {'required':req}
    RETURN_TYPES = ('DOGMA_LAB_RESULTS',)
    FUNCTION = 'run'
    CATEGORY = 'DOGMA/Mask lab 1.0.15'

    def check_lazy_status(self, plan, model=None, clip=None, **kwargs):
        if not plan['items'] or not any(kwargs.get('run_'+x,True) for x in 'ABCDE'):
            return []
        return [k for k,v in (('model',model),('clip',clip)) if v is None]

    def run(self,image,plan,analysis_side,score_threshold,max_instances,max_mask_coverage,
            min_box_agreement,refinement_budget,tile_overlap,reverse_order,rerun,
            run_A,run_B,run_C,run_D,run_E,model=None,clip=None):
        import torch
        import comfy.utils
        from nodes import CLIPTextEncode
        source = resize_image(image,analysis_side)
        methods = [x for x,enabled in zip('ABCDE',(run_A,run_B,run_C,run_D,run_E)) if enabled]
        if reverse_order:
            methods.reverse()
        result = dict(image=source, plan=plan, methods=[], shared_seconds=0.,
                      original_size=list(image.shape[1:3]), analysis_size=list(source.shape[1:3]),
                      settings=dict(threshold=score_threshold,cap=max_instances,max_coverage=max_mask_coverage,
                                    min_box_agreement=min_box_agreement,refinement_budget=refinement_budget,
                                    tile_overlap=tile_overlap), elapsed=0.)
        if not plan['items'] or not methods:
            return (result,)
        started = time.perf_counter()
        encodings = {}
        with torch.inference_mode():
            for row in plan['items']:
                for query in [row['primary']] + ([row['secondary']] if run_C else []):
                    if query not in encodings:
                        interrupted()
                        cond = CLIPTextEncode().encode(clip,query)[0]
                        emb, meta = cond[0]
                        if meta.get('sam3_multi_cond'):
                            entry = meta['sam3_multi_cond'][0]
                            emb, mask = entry['cond'], entry.get('attention_mask')
                        else:
                            mask = meta.get('attention_mask')
                        encodings[query] = (emb.detach().cpu(),mask.detach().cpu() if mask is not None else None)
            # Text encoding is completed before loading SAM to avoid model swaps per query.
            session = SAMSession(model,encodings)
            sync()
            result['shared_seconds'] = time.perf_counter()-started
            try:
                progress = comfy.utils.ProgressBar(len(methods))
                for method_index, method in enumerate(methods):
                    interrupted()
                    print(f'[DOGMA mask lab] {METHODS[ord(method)-65]}: start', flush=True)
                    session.backbones = session.detections = session.refinements = 0
                    sync()
                    tick = time.perf_counter()
                    entries = execute_method(session,source,plan['items'],method,score_threshold,max_instances,
                                             max_mask_coverage,min_box_agreement,refinement_budget,tile_overlap)
                    sync()
                    elapsed = time.perf_counter()-tick
                    result['methods'].append(dict(key=method,label=METHODS[ord(method)-65],entries=entries,
                                                  seconds=elapsed,backbones=session.backbones,
                                                  detections=session.detections,refinements=session.refinements))
                    session.clear()
                    progress.update_absolute(method_index + 1, len(methods))
                    print(f'[DOGMA mask lab] {method}: {elapsed:.2f}s', flush=True)
            finally:
                session.clear()
        result['elapsed'] = time.perf_counter()-started
        return (result,)


class DOGMAMaskLabReportV115:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'results':('DOGMA_LAB_RESULTS',),
                            'save_reports':('BOOLEAN',{'default':True})}}
    RETURN_TYPES = ('IMAGE','IMAGE','STRING')
    RETURN_NAMES = ('comparison_per_category','overview','timing_and_diagnostics')
    FUNCTION = 'build'
    CATEGORY = 'DOGMA/Mask lab 1.0.15'

    def build(self, results, save_reports=True):
        import numpy as np
        import torch
        from PIL import Image,ImageDraw,ImageFont
        methods = sorted(results['methods'],key=lambda m:m['key'])
        h,w = results['image'].shape[1:3]
        base = (results['image'][0].clamp(0,1).numpy()*255).astype(np.uint8)
        width = 440
        height = max(100,round(h/w*width))
        original = Image.fromarray(base).resize((width,height))
        try:
            font = ImageFont.truetype('DejaVuSans.ttf',18)
        except OSError:
            try:
                font = ImageFont.truetype('arial.ttf',18)
            except OSError:
                font = ImageFont.load_default()
        sheets = []
        report = {k:v for k,v in results.items() if k not in ('image','methods')}
        report['methods'] = []
        lines = ['MASK LAB: timings are measured on this run, not GPU speed guarantees.',
                 f"Inventory: {results['plan']['seconds']:.2f}s | shared text/model setup: {results['shared_seconds']:.2f}s",
                 'Methods measured separately with new image features; model remains loaded. Reverse order / rerun to check warm-up effects.',
                 'CheckpointLoader disk time and report/image saving are outside these timings; see ComfyUI node/queue durations for end-to-end cost.',
                 'Geometry flags are heuristics, NOT semantic validation. Coverage is NOT accuracy. Red=excluded after detection; cyan=retained. Below-confidence candidates are not shown.',
                 'No per-mask VLM audits, no diffusion, no hole filling, no morphological closing.',
                 f"Original HxW {results['original_size']}; masks HxW {results['analysis_size']}. No claim of native full-resolution detail."]
        csv_rows = []
        for method in methods:
            data = {k:v for k,v in method.items() if k!='entries'}
            data['entries'] = []
            lines.append(f"{method['label']}: {method['seconds']:.2f}s; image encodes {method['backbones']}; text searches {method['detections']}; decoder calls {method['refinements']}")
            for entry in method['entries']:
                stats = {k:v for k,v in entry.items() if k not in ('mask','rejected')}
                stats['coverage_percent'] = 100*float(entry['mask'].float().mean())
                data['entries'].append(stats)
                csv_rows.append([method['key'],entry['category'],round(method['seconds'],3),entry['detected'],entry['kept'],round(stats['coverage_percent'],3),' | '.join(entry['notes'])])
                lines.append(f"  {entry['category']}: candidates {entry['detected']} retained {entry['kept']}, coverage {stats['coverage_percent']:.2f}% | "+'; '.join(dict.fromkeys(entry['notes'])))
            report['methods'].append(data)
        for ci,row in enumerate(results['plan']['items'] if methods else []):
            canvas = Image.new('RGB',(width*max(1,len(methods)),105+height*3+145),(24,28,33))
            draw = ImageDraw.Draw(canvas)
            draw.text((12,8),f"CATEGORY: {row['category']} | top=original / middle=mask / bottom=overlay (red=rejected)",font=font,fill='white')
            for mi,method in enumerate(methods):
                e = method['entries'][ci]
                mask = e['mask'].numpy()
                rejected = e['rejected'].numpy() & ~mask
                overlay = base.astype(np.float32)*.65
                overlay[mask] = base[mask]*.55+np.array([0,210,230])*.45
                overlay[rejected] = base[rejected]*.55+np.array([255,55,55])*.45
                pics = [original,Image.fromarray(mask.astype(np.uint8)*255).convert('RGB').resize((width,height),Image.Resampling.NEAREST),
                        Image.fromarray(overlay.clip(0,255).astype(np.uint8)).resize((width,height))]
                x=mi*width
                draw.text((x+8,42),method['label'],font=font,fill=(130,220,225))
                draw.text((x+8,70),f"{method['seconds']:.2f}s | coverage {mask.mean()*100:.1f}%",font=font,fill='white')
                for pi,picture in enumerate(pics):
                    canvas.paste(picture,(x,105+pi*height))
                y=110+3*height
                notes = ['NO MASK' if not mask.any() else 'Inspect boundaries / missed objects'] + list(dict.fromkeys(e['notes']))
                import textwrap
                text='\n'.join(textwrap.wrap(' | '.join(notes),48)[:6])
                draw.multiline_text((x+8,y),text,font=font,fill=(240,210,160))
            sheets.append(torch.from_numpy(np.asarray(canvas).copy()).float()[None]/255)
        if not sheets:
            canvas=Image.new('RGB',(900,180),(24,28,33))
            ImageDraw.Draw(canvas).text((20,50),'No categories or no enabled methods. Inspect the inventory.',font=font,fill='white')
            sheets=[torch.from_numpy(np.asarray(canvas).copy()).float()[None]/255]
        # Overview preserves the same category and method order as detailed sheets.
        thumbs=[Image.fromarray((s[0].numpy()*255).astype(np.uint8)).resize((1100,round(s.shape[1]/s.shape[2]*1100))) for s in sheets]
        overview=Image.new('RGB',(1100,sum(t.height for t in thumbs)),(24,28,33))
        y=0
        for thumb in thumbs:
            overview.paste(thumb,(0,y))
            y+=thumb.height
        if save_reports:
            import folder_paths
            import uuid
            dest=Path(folder_paths.get_output_directory())/'DOGMA_MASK_LAB'
            dest.mkdir(parents=True,exist_ok=True)
            stem=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
            mask_dir=dest/stem
            mask_dir.mkdir()
            Image.fromarray(base).save(mask_dir/'analysis_source.png')
            for method in methods:
                for ci,entry in enumerate(method['entries'],1):
                    name=re.sub('[^a-zA-Z0-9_-]','_',entry['category'])[:60]
                    for field in ('mask','rejected'):
                        path=mask_dir/f'{method["key"]}_{ci:02d}_{name}_{field}.png'
                        Image.fromarray(entry[field].numpy().astype(np.uint8)*255).save(path)
            report['mask_directory']=str(mask_dir)
            (dest/(stem+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            with (dest/(stem+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream)
                writer.writerow(['method','category','method_seconds','candidates','retained','coverage_percent','notes'])
                writer.writerows(csv_rows)
            lines.append('Reports saved: '+str(dest/(stem+'.json')))
        return torch.cat(sheets),torch.from_numpy(np.asarray(overview).copy()).float()[None]/255,'\n'.join(lines)


NODE_CLASS_MAPPINGS = {c.__name__:c for c in (DOGMAMaskLabPlanV115,DOGMAMaskLabRunV115,DOGMAMaskLabReportV115)}
NODE_DISPLAY_NAME_MAPPINGS = {k:k.replace('DOGMA','DOGMA ').replace('V115',' 1.0.15') for k in NODE_CLASS_MAPPINGS}
