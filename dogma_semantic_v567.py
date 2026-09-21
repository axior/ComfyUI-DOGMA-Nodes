"""DOGMA 1.0.6: raw SAM search, local recovery, per-instance review.

Memory management is deliberately delegated to KJNodes in the workflow.
This module never downloads models, changes Comfy internals or frees models.
"""
import copy
import math
import re

import numpy as np
import torch
import torch.nn.functional as F
from scipy import ndimage


def canonical(text):
    value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", str(text)).strip().lower()
    value = value.strip('`" .')
    groups = {
        'buildings': ('buildings', 'building', 'architecture', 'facade', 'facades', 'houses'),
        'vehicles': ('vehicle', 'vehicles', 'car', 'cars', 'bus', 'buses', 'truck', 'trucks', 'van', 'vans'),
        'people': ('people', 'person', 'persons', 'pedestrian', 'pedestrians'),
        'road': ('road', 'roads', 'street', 'streets', 'pavement'),
    }
    for key, words in groups.items():
        if value in words:
            return key
    return value or 'none'


def inactive(category):
    return canonical(category) in {'none', 'unused', 'n/a', 'absent'}


def queries(category):
    c = canonical(category)
    return {
        'buildings': ['building', 'building facade'],
        'vehicles': ['vehicle', 'car', 'bus', 'truck'],
        'people': ['person', 'pedestrian'],
        'road': ['road', 'pavement'],
        'vegetation': ['tree', 'plant'],
    }.get(c, [c])


def structural(category):
    return bool(set(re.findall(r'[a-z]+', canonical(category))) &
                {'buildings', 'building', 'house', 'cathedral', 'bridge', 'tower', 'facade'})


class DOGMASemanticPlanV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'planner_text': ('STRING', {'forceInput': True})}}
    RETURN_TYPES = ('STRING',) + ('STRING', 'STRING', 'FLOAT') * 5
    RETURN_NAMES = ('plan_preview',) + tuple(x for i in range(1, 6) for x in
                      (f'category_{i}', f'sam_prompt_{i}', f'sam_threshold_{i}'))
    FUNCTION = 'build'
    CATEGORY = 'DOGMA/v56.7'

    def build(self, planner_text):
        cats = []
        for line in str(planner_text).splitlines():
            c = canonical(line)
            if inactive(c) or c in cats:
                continue
            if len(c.split()) > 4 or re.search(r'\b(noise|blur|artifact|background|foreground|quality|signage|text)\b', c):
                continue
            cats.append(c)
        if not cats:
            raise ValueError('DOGMA: the scene inventory contains no usable categories. Check the planner preview.')
        cats = cats[:5]
        outputs = []
        for c in cats + ['none'] * (5 - len(cats)):
            outputs.extend([c, queries(c)[0], .25])
        preview = f'{len(cats)} visible categories; unused slots are explicitly inactive.\n' + '\n'.join(
            f'{i+1}: {c}' for i, c in enumerate(cats))
        return (preview, *outputs)


def local_windows(h, w):
    """Four overlapping views; cover every pixel, without a downscaled full scene."""
    th, tw = max(1, math.ceil(h * .64)), max(1, math.ceil(w * .64))
    return list(dict.fromkeys((x, y, min(w, x+tw), min(h, y+th))
                for y in (0, h-th) for x in (0, w-tw)))


def clean_instances(masks, boxes, h, w, threshold, category, source):
    """Clip to paired detector boxes; remove islands without dilating or filling holes."""
    masks = masks.detach().float().cpu()
    if masks.ndim == 2:
        masks = masks[None]
    if isinstance(boxes, list) and len(boxes) == 1 and isinstance(boxes[0], list):
        boxes = boxes[0]
    if masks.ndim != 3 or tuple(masks.shape[-2:]) != (h, w):
        raise ValueError('DOGMA: SAM masks have unexpected dimensions.')
    if not isinstance(boxes, list) or len(boxes) != len(masks):
        raise ValueError('DOGMA: SAM mask/box counts differ; cannot pair instances safely.')
    items, notes = [], []
    for index, (m, b) in enumerate(zip(masks, boxes)):
        try:
            x, y, bw, bh, score = [float(b[k]) for k in ('x', 'y', 'width', 'height', 'score')]
            if not all(math.isfinite(v) for v in (x, y, bw, bh, score)) or bw <= 0 or bh <= 0 or score < threshold:
                raise ValueError('score/box')
            x0, y0 = max(0, math.floor(x)), max(0, math.floor(y))
            x1, y1 = min(w, math.ceil(x+bw)), min(h, math.ceil(y+bh))
            if x1 <= x0 or y1 <= y0:
                raise ValueError('outside image')
            if not torch.isfinite(m).all() or m.min() < 0 or m.max() > 1:
                raise ValueError('not a probability mask')
        except (KeyError, TypeError, ValueError, OverflowError):
            notes.append(f'{source} #{index+1}: invalid box/score/mask')
            continue
        roi = m[y0:y1, x0:x1].numpy() >= .5
        labels, count = ndimage.label(roi, np.ones((3, 3), np.uint8))
        if not count:
            continue
        sizes = np.bincount(labels.ravel()); sizes[0] = 0
        largest = int(sizes.max()); total = int(sizes.sum())
        floor = max(3, math.ceil(largest * .005))
        selected = np.isin(labels, np.flatnonzero(sizes >= floor))
        # Large fragmented detections are re-searched locally, not expanded by closing.
        diffuse = bw*bh > .30*h*w and largest/max(1, total) < .45
        if selected.sum() < 9 or diffuse:
            notes.append(f'{source} #{index+1}: fragmented/tiny, needs local search')
            continue
        mask = torch.zeros((h, w), dtype=torch.bool)
        mask[y0:y1, x0:x1] = torch.from_numpy(selected)
        items.append(dict(mask=mask, score=score, source=source))
    return items, notes


def deduplicate(items, already=(), limit=48):
    # Prefer larger complete instances; contained tiled fragments are redundant.
    result = []
    def geometry(item):
        mask = item['mask'].numpy()
        ys = np.flatnonzero(mask.any(1)); xs = np.flatnonzero(mask.any(0))
        bounds = (int(xs[0]), int(ys[0]), int(xs[-1])+1, int(ys[-1])+1) if len(xs) else (0,0,0,0)
        return (mask, int(np.count_nonzero(mask)), bounds)
    # Compare intersections only in the shared bounding region, not full 2.5K
    # masks for every pair. Nothing is cached inside serialized Comfy data.
    cache = {id(i): geometry(i) for i in list(items)+list(already)}
    ordered = sorted(items, key=lambda i: (-cache[id(i)][1], -i['score']))
    references = list(already)
    for item in ordered:
        m, area, a = cache[id(item)]
        if not area:
            continue
        duplicate = False
        for other in references + result:
            n, _, b = cache[id(other)]
            x0,y0,x1,y1 = max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])
            if x1<=x0 or y1<=y0:continue
            overlap = np.count_nonzero(m[y0:y1,x0:x1] & n[y0:y1,x0:x1])
            # Only discard if THIS candidate is almost entirely represented.
            if overlap / area >= .90:
                duplicate = True
                break
        if not duplicate:
            result.append(item)
    if len(result) > limit:
        raise ValueError(f'DOGMA: {len(result)} distinct instances exceed the review limit {limit}. Increase max_instances; none were silently dropped.')
    return result


class DOGMASAMSearchV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',), 'model': ('MODEL',), 'clip': ('CLIP',),
            'category': ('STRING', {'forceInput': True}),
            'mode': (['global', 'local_recovery'],),
            'threshold': ('FLOAT', {'default': .25, 'min': .05, 'max': .9, 'step': .01}),
            'max_instances': ('INT', {'default': 48, 'min': 8, 'max': 128})},
            'optional': {'previous': ('DOGMA_REVIEW',), 'after': ('STRING', {'forceInput': True})}}
    RETURN_TYPES = ('DOGMA_CANDIDATES', 'STRING')
    RETURN_NAMES = ('candidates', 'search_report')
    FUNCTION = 'search'
    CATEGORY = 'DOGMA/v56.7'

    @staticmethod
    def _detect(model, clip, image, query, threshold, max_instances):
        from nodes import CLIPTextEncode
        from comfy_extras.nodes_sam3 import SAM3_Detect
        conditioning = CLIPTextEncode().encode(clip, query)[0]
        meta = dict(conditioning[0][1])
        entries = meta.get('sam3_multi_cond')
        if entries is None:
            entries = [dict(cond=conditioning[0][0], attention_mask=meta.get('attention_mask'))]
        meta['sam3_multi_cond'] = [dict(e, max_detections=int(max_instances)) for e in entries]
        conditioning = [[conditioning[0][0], meta]]
        # Raw detector masks avoid the core refinement OR retaining noisy coarse pixels.
        result = SAM3_Detect.execute(model=model, image=image, conditioning=conditioning,
                    threshold=threshold, refine_iterations=0, individual_masks=True)
        return result[0], result[1]

    def search(self, image, model, clip, category, mode='global', threshold=.25,
               max_instances=48, previous=None, after=None):
        if image.ndim != 4 or image.shape[0] != 1:
            raise ValueError('DOGMA semantic restoration requires a single image.')
        category = canonical(category); h, w = image.shape[1:3]
        accepted = list(previous['accepted']) if previous else []
        if previous and (previous['category'] != category or previous['shape'] != (h, w)):
            raise ValueError('DOGMA: recovery input belongs to a different category/image size.')
        if mode == 'local_recovery' and previous is None:
            raise ValueError('DOGMA: local recovery requires the first instance review.')
        notes = list(previous.get('notes', [])) if previous else []
        items = []; calls = 0
        if not inactive(category):
            views = [(0, 0, w, h)] if mode == 'global' else local_windows(h, w)
            aliases = queries(category)
            for view, (x0, y0, x1, y1) in enumerate(views):
                crop = image[:, y0:y1, x0:x1, :3]
                found_here = 0
                # Both global nouns; local pass tries the alternate noun when empty.
                for q, query in enumerate(aliases if mode == 'global' else aliases[:2]):
                    if mode == 'local_recovery' and q > 0 and found_here:
                        break
                    raw, boxes = self._detect(model, clip, crop, query, threshold, max_instances)
                    calls += 1
                    cleaned, failures = clean_instances(raw, boxes, y1-y0, x1-x0,
                                          threshold, category, f'{mode}/{view+1}/{query}')
                    notes.extend(failures); found_here += len(cleaned)
                    for item in cleaned:
                        full = torch.zeros((h, w), dtype=torch.bool)
                        full[y0:y1, x0:x1] = item['mask']
                        item['mask'] = full; items.append(item)
        items = deduplicate(items, accepted, int(max_instances))
        report = f'{category}: {mode}, {calls} SAM calls; {len(items)} new candidates, {len(accepted)} already approved. Raw masks; no dilation or hole filling.'
        bundle = dict(category=category, shape=(h, w), items=items, accepted=accepted,
                      notes=notes + [report])
        return (bundle, report)


class DOGMAInstanceAuditViewV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',), 'candidates': ('DOGMA_CANDIDATES',),
            'panel_size': ('INT', {'default': 512, 'min': 256, 'max': 768, 'step': 64})}}
    RETURN_TYPES = ('IMAGE', 'STRING')
    RETURN_NAMES = ('instance_sheets', 'audit_instructions')
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = 'build'
    CATEGORY = 'DOGMA/v56.7'

    def build(self, image, candidates, panel_size=512):
        h, w = candidates['shape']
        src = image[:1, ..., :3].detach().float().cpu()
        src = F.interpolate(src.movedim(-1, 1), size=(h, w), mode='bilinear', align_corners=False).movedim(1, -1)
        sheets, prompts = [], []
        for item in candidates['items']:
            mask = item['mask']; ys, xs = torch.where(mask)
            margin = max(16, round(.12 * max(int(xs.max()-xs.min()+1), int(ys.max()-ys.min()+1))))
            x0, x1 = max(0, int(xs.min())-margin), min(w, int(xs.max())+margin+1)
            y0, y1 = max(0, int(ys.min())-margin), min(h, int(ys.max())+margin+1)
            crop = src[:, y0:y1, x0:x1]; m = mask[None, y0:y1, x0:x1, None].float()
            cyan = torch.tensor([0., .9, 1.]).view(1, 1, 1, 3)
            panels = [crop, m.expand(-1,-1,-1,3), crop*(1-.5*m)+cyan*.5*m, crop*m+.25*(1-m)]
            scale = panel_size/max(y1-y0, x1-x0)
            size = (max(16, round((y1-y0)*scale)), max(16, round((x1-x0)*scale)))
            small = [F.interpolate(p.movedim(-1,1), size=size, mode='bilinear', align_corners=False).movedim(1,-1) for p in panels]
            sheets.append(torch.cat([torch.cat(small[:2], 2), torch.cat(small[2:], 2)], 1))
            prompts.append(
                f'Check ONE candidate mask for "{candidates["category"]}". '
                'The 2x2 sheet shows: original crop, white mask, cyan overlay, selected pixels on gray. '
                'Judge only the selected pixels. PASS when the selection mainly follows a visible instance or coherent part '
                'of the named category. Partial buildings, occluded objects, windows within a facade and disconnected visible '
                'parts of the same object are valid. The mask need not cover every instance in the crop. '
                'FAIL for substantial selection of a DIFFERENT semantic class, scattered patches on unrelated surfaces, '
                'or no visible target. Never reject the target class itself as background. '
                'Respond PASS or FAIL, then a short reason. No editing instructions.')
        if not sheets:
            # A single sentinel maintains list alignment; reviewer ignores it because there are zero candidates.
            sheets = [torch.zeros((1, 64, 64, 3))]
            prompts = ['No candidate mask in this stage. Return FAIL.']
        return (sheets, prompts)


def verdict(text):
    text = re.sub(r'<think>.*?</think>', '', str(text), flags=re.S|re.I).strip().strip('`* \n')
    match = re.match(r'^(PASS|FAIL)\b', text, re.I)
    if not match:
        return False
    return match[1].upper() == 'PASS' and not re.search(r'\bFAIL\b', text, re.I)


class DOGMAInstanceReviewV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'candidates': ('DOGMA_CANDIDATES',), 'audit_text': ('STRING', {'forceInput': True})}}
    RETURN_TYPES = ('DOGMA_REVIEW', 'STRING')
    RETURN_NAMES = ('review', 'audit_report')
    INPUT_IS_LIST = True
    FUNCTION = 'review'
    CATEGORY = 'DOGMA/v56.7'

    def review(self, candidates, audit_text):
        if len(candidates) != 1:
            raise ValueError('DOGMA: instance review expects one candidate bundle.')
        data = candidates[0]; items = data['items']; accepted = list(data['accepted'])
        if items and len(audit_text) != len(items):
            raise ValueError(f'DOGMA: {len(items)} masks but {len(audit_text)} audit answers. No guessing by position.')
        lines = []
        for i, (item, text) in enumerate(zip(items, audit_text), 1):
            ok = verdict(text)
            if ok:
                accepted.append(item)
            lines.append(f'#{i} {item["source"]}: {"PASS" if ok else "RETRY/REJECT"} {str(text)[:200]}')
        result = dict(category=data['category'], shape=data['shape'], accepted=accepted,
                      notes=data['notes']+lines)
        return (result, '\n'.join(result['notes']))


class DOGMAAuditTextV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'candidates': ('DOGMA_CANDIDATES',),
            'audit_text': ('STRING', {'forceInput': True, 'lazy': True})}}
    RETURN_TYPES = ('STRING',)
    OUTPUT_IS_LIST = (True,)
    INPUT_IS_LIST = True
    FUNCTION = 'choose'
    CATEGORY = 'DOGMA/v56.7'

    def check_lazy_status(self, candidates, audit_text=None):
        # Comfy passes (None,) for a missing lazy input on INPUT_IS_LIST nodes.
        missing = audit_text is None or any(x is None for x in audit_text)
        return ['audit_text'] if candidates[0]['items'] and missing else []

    def choose(self, candidates, audit_text=None):
        return (audit_text if candidates[0]['items'] else [],)


class DOGMALazyImageV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'fallback': ('IMAGE',), 'masks': ('MASK',),
            'result': ('IMAGE', {'lazy': True})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'choose'
    CATEGORY = 'DOGMA/v56.7'

    def check_lazy_status(self, fallback, masks, result=None):
        return ['result'] if masks.numel() and bool((masks >= .5).any()) and result is None else []

    def choose(self, fallback, masks, result=None):
        return (result if masks.numel() and bool((masks >= .5).any()) else fallback,)


class DOGMALazyTextV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'masks': ('MASK',), 'text': ('STRING', {'forceInput': True, 'lazy': True})}}
    RETURN_TYPES = ('STRING',)
    FUNCTION = 'choose'
    CATEGORY = 'DOGMA/v56.7'

    def check_lazy_status(self, masks, text=None):
        return ['text'] if masks.numel() and bool((masks >= .5).any()) and text is None else []

    def choose(self, masks, text=None):
        return (str(text) if masks.numel() and bool((masks >= .5).any()) else 'INACTIVE SLOT: no category; caption and diffusion not executed.',)


class DOGMAFinalMasksV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'review': ('DOGMA_REVIEW',)}}
    RETURN_TYPES = ('MASK', 'STRING')
    RETURN_NAMES = ('approved_instances', 'report')
    FUNCTION = 'finish'
    CATEGORY = 'DOGMA/v56.7'

    def finish(self, review):
        items = deduplicate(review['accepted'], limit=256)
        category = review['category']; h, w = review['shape']
        if not items and not inactive(category):
            raise ValueError(f'DOGMA: category "{category}" has no verified mask after global AND local recovery. '
                'Restoration stopped before diffusion, rather than silently omitting this category. '
                'See SEARCH / AUDIT previews.\n' + '\n'.join(review['notes'])[-3500:])
        masks = torch.stack([i['mask'] for i in items]).float() if items else torch.zeros((0,h,w))
        summary = f'{category}: {len(items)} verified instances after global + overlapping local search.'
        return (masks, summary+'\n'+'\n'.join(review['notes']))


class DOGMAMaskOwnershipV567:
    @classmethod
    def INPUT_TYPES(cls):
        req = {}
        for i in range(1,6):
            req[f'mask_{i}'] = ('MASK',)
            req[f'category_{i}'] = ('STRING', {'forceInput': True})
        return {'required': req}
    RETURN_TYPES = ('MASK',)*5 + ('STRING',)
    RETURN_NAMES = tuple(f'mask_{i}' for i in range(1,6)) + ('ownership_report',)
    FUNCTION = 'resolve'
    CATEGORY = 'DOGMA/v56.7'

    def resolve(self, **kwargs):
        masks = [kwargs[f'mask_{i}'].detach().cpu() >= .5 for i in range(1,6)]
        cats = [canonical(kwargs[f'category_{i}']) for i in range(1,6)]
        shape = masks[0].shape[-2:]
        if any(m.ndim != 3 or m.shape[-2:] != shape for m in masks):
            raise ValueError('DOGMA: ownership masks must use the same analysis image dimensions.')
        def priority(i):
            c = cats[i]
            if c == 'people': return 0
            if c == 'vehicles': return 1
            if structural(c): return 3
            if c in {'road','ground','pavement','floor','water','grass','vegetation','sky'}: return 4
            return 2
        occupied = torch.zeros(shape, dtype=torch.bool); out = [None]*5; lines = []
        for i in sorted(range(5), key=priority):
            m = masks[i] & ~occupied
            if m.numel():
                m = m[m.flatten(1).sum(1) >= 9]
            if len(m): occupied |= m.any(0)
            if len(masks[i]) and not len(m) and not inactive(cats[i]):
                raise ValueError(f'DOGMA: {cats[i]} was fully covered by other categories. Check conflicting detections before diffusion.')
            out[i] = m.float()
            lines.append(f'{cats[i]}: {len(m)} instances, exclusive ownership; removed {int(masks[i].sum()-m.sum())} overlapping pixels.')
        return (*out, '\n'.join(lines))


class DOGMAImageAfterAuditV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',), 'audit_report': ('STRING', {'forceInput': True})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'wait'
    CATEGORY = 'DOGMA/v56.7'

    def wait(self, image, audit_report):
        return (image,)


class DOGMATileBundleV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'tiles': ('IMAGE',), 'prompts': ('STRING', {'forceInput': True}),
                             'reports': ('STRING', {'forceInput': True})}}
    RETURN_TYPES = ('DOGMA_TILE_BUNDLE',)
    INPUT_IS_LIST = True
    FUNCTION = 'pack'
    CATEGORY = 'DOGMA/v56.7'

    def pack(self, tiles, prompts, reports):
        if not len(tiles) == len(prompts) == len(reports):
            raise ValueError('DOGMA: tile/caption list alignment lost before memory cleanup.')
        return (dict(tiles=tiles, prompts=prompts, reports=reports),)


class DOGMATileUnpackV567:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'bundle': ('DOGMA_TILE_BUNDLE',)}}
    RETURN_TYPES = ('IMAGE', 'STRING', 'STRING')
    RETURN_NAMES = ('tiles', 'prompts', 'preview')
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION = 'unpack'
    CATEGORY = 'DOGMA/v56.7'

    def unpack(self, bundle):
        preview = '\n\n'.join(f'TILE {i+1}\nCAPTION: {r}\nPROMPT: {p}' for i, (r,p) in enumerate(zip(bundle['reports'],bundle['prompts'])))
        return (bundle['tiles'], bundle['prompts'], preview)


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (
    DOGMASemanticPlanV567, DOGMASAMSearchV567, DOGMAInstanceAuditViewV567,
    DOGMAInstanceReviewV567, DOGMAFinalMasksV567, DOGMAMaskOwnershipV567,
    DOGMAImageAfterAuditV567, DOGMATileBundleV567, DOGMATileUnpackV567,
    DOGMAAuditTextV567, DOGMALazyImageV567, DOGMALazyTextV567)}
NODE_DISPLAY_NAME_MAPPINGS = {name: name.replace('DOGMA','DOGMA ').replace('V567',' v56.7') for name in NODE_CLASS_MAPPINGS}
