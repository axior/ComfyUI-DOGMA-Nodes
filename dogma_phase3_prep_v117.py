"""Standalone phase-3 preparation: open inventory, B masks, choice, crops, captions.

No diffusion, model downloads, or changes to existing production node behavior.
"""
import copy
import csv
import json
import re
import sys
import time
import uuid
from pathlib import Path


def node(name):
    import nodes
    return nodes.NODE_CLASS_MAPPINGS[name]


def lab():
    return sys.modules[node('DOGMAMaskLabPlanV115').__module__]


def vlm_settings():
    schema = copy.deepcopy(node('ModernVLM').INPUT_TYPES()['required'])
    return {k: schema[k] for k in ('model', 'custom_model_id', 'memory_mode')}


def inventory_prompt(limit):
    return f'''Produce a compact semantic inventory for editing this photograph.
Survey the ENTIRE frame: foreground, middle distance, far background and all four image borders. Do not stop after identifying the main subject.
Describe the overall scene in two sentences, then make TWO inventories:
"objects": distinct types of complete visible objects. Keep different object types separate even if they share a broad family. Name the containing whole object rather than its attached components or decorative details, including partly visible whole objects.
"surfaces": visible continuous environmental regions and background expanses. Include regions along image borders even if narrow, dark, distant or low in detail. These are independent editing regions, not object components or lighting effects.
Use only what is visibly supported. Do not infer hidden regions or fill a quota. Use short English noun phrases, no proper names or positions. Combine duplicate names, never different object types.
Maximum {limit} entries across both inventories. Return ONLY JSON with "scene" (two sentences), "objects" (array of names) and "surfaces" (array of names).'''


def parse_groups(text, limit):
    """One image-derived type per work target. Never union children of a family."""
    raw = lab().clean_inventory(text)
    try:
        value, end = json.JSONDecoder().raw_decode(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError('DOGMA: invalid target inventory. Expected JSON targets, not semantic families. '
                         'Use the V5 Qwen 3 VL 8B preset or inspect RAW: ' + raw[:800]) from exc
    notes = []
    if raw[end:].strip():
        if raw[end:].strip() not in ('"', "'"):
            raise ValueError('DOGMA: unexpected text after semantic inventory: ' + raw[end:end+200])
        notes.append('Ignored a trailing quote after the complete JSON object.')
    if not isinstance(value, dict) or not isinstance(value.get('targets'), list):
        raise ValueError('DOGMA: expected a JSON targets array. Old grouped inventories must be regenerated.')
    groups = {}
    def noun(value):
        if not isinstance(value, str):
            raise ValueError('DOGMA: category names and object searches must be strings.')
        value = ' '.join(value.lower().strip().split())
        if not re.fullmatch(r'[a-z][a-z0-9 -]{0,79}', value) or len(value.split()) > 6:
            raise ValueError('DOGMA: invalid short noun in inventory: ' + value[:100])
        return value
    for row in value['targets'][:64]:
        name = noun(row)
        if name in groups:
            notes.append('Repeated target name removed: ' + name)
        groups[name] = name
    result = []
    for name in groups:
        result.append(dict(category=name,query=name,queries=[name],target_id=f't{len(result)+1:03d}',evidence='Qwen independent object type'))
    if len(result) > limit:
        notes.append(f'Target budget: omitted {", ".join(r["category"] for r in result[limit:])}; increase max_categories.')
    if len(value['targets']) > 64:
        notes.append('Inventory row limit reached; excess targets omitted.')
    return result[:limit], notes


def consolidate_prompt(draft, limit):
    cleaned = lab().clean_inventory(draft)
    try:
        observation,_ = json.JSONDecoder().raw_decode(cleaned)
        scene = observation['scene']
        objects = observation['objects']
        surfaces = observation['surfaces']
        if not isinstance(scene,str) or not scene.strip() or not isinstance(objects,list) or not isinstance(surfaces,list):
            raise ValueError('missing inventory')
        if any(not isinstance(x,str) or not x.strip() for x in objects+surfaces):
            raise ValueError('invalid inventory entry')
    except (ValueError,KeyError,TypeError) as exc:
        raise ValueError('DOGMA: missing full-frame object/surface inventory; inspect the visual draft.') from exc
    return ('Normalize EVERY object AND surface candidate below into an independent editing target. '
            'The two candidate lists are provisional observations, NOT an approved classification. '
            'If it names an attached part, use the containing whole object supported by the scene. '
            'When that containing object is already a candidate, reuse its EXACT normalized target name. '
            'A structural support, decoration, or exterior surface attached to a larger object must map to '
            'that whole object, even when mistakenly listed under surfaces. Do not create both part and whole '
            'as editing targets. Preserve a part only if its containing object cannot be identified from the image. '
            'Keep genuinely different complete object types separate. Do not collapse them into a parent family. '
            'Keep independently visible environmental regions, including narrow or dark background regions. '
            'Remove positional and lighting adjectives; invent no objects. A generic scene label is not an editing target. '
            'Return ONLY JSON with an "objects" array of {"source":"exact candidate name","target":"whole object type"}. '
            'For a nonphysical scene label or unsupported candidate use "target":null and a short "reason"; never silently omit it. '
            'Account for every supplied candidate exactly once.\n'
            'SCENE DESCRIPTION:\n'+scene+'\nOBJECT CANDIDATES:\n'+json.dumps(objects,ensure_ascii=False)
            +'\nSURFACE CANDIDATES:\n'+json.dumps(surfaces,ensure_ascii=False))


def normalized_inventory(draft, normalized, limit):
    """Account for every observation, including surfaces; no summary-only loss."""
    consolidate_prompt(draft,limit)  # Validate the complete first observation.
    observation,_ = json.JSONDecoder().raw_decode(lab().clean_inventory(draft))
    notes = []
    candidates = observation['objects']+observation['surfaces']
    def key(value):return ' '.join(value.lower().split())
    originals = {key(x):x for x in candidates}
    mapping = {}
    try:
        response = json.loads(lab().clean_inventory(normalized))
        rewrites = response if isinstance(response,list) else response.get('objects') if isinstance(response,dict) else None
        if not isinstance(rewrites,list):raise ValueError('missing object rewrites')
        if isinstance(response,dict) and isinstance(response.get('surfaces'),list):
            rewrites = rewrites+response['surfaces']
        for row in rewrites:
            if not isinstance(row,dict) or not isinstance(row.get('source'),str):
                notes.append('Invalid object rewrite ignored; original candidate retained.')
                continue
            source = key(row['source'])
            if source not in originals:
                notes.append('Unsupported normalization source ignored: '+source)
                continue
            if row.get('target') is None and isinstance(row.get('reason'),str) and row['reason'].strip():
                mapping[source] = None
                notes.append(f'Explicitly excluded candidate {source}: {row["reason"][:200]}')
                continue
            try:
                clean,_ = parse_groups(json.dumps({'targets':[row['target']]}),1)
                if not clean:raise ValueError('empty rewrite')
            except (ValueError,KeyError,TypeError):
                notes.append('Invalid normalized name; original retained: '+source)
                continue
            if source in mapping and mapping[source]!=clean[0]['category']:
                mapping[source] = key(originals[source])
                notes.append('Conflicting rewrites; original retained: '+source)
            else:
                mapping[source] = clean[0]['category']
    except (ValueError,TypeError):
        notes.append('Normalization unusable; original observed candidates retained, review their granularity.')
    targets = []
    for original in candidates:
        name = key(original)
        if name not in mapping:
            notes.append('Unaccounted object retained: '+name)
        target = mapping.get(name,name)
        if target is not None:
            targets.append(target)
    rows,parse_notes = parse_groups(json.dumps({'targets':targets}),limit)
    surfaces = {mapping.get(key(x),key(x)) for x in observation['surfaces']}
    for row in rows:
        row['evidence'] = 'Full-frame surface observation' if row['category'] in surfaces else 'Normalized whole object'
        row['observed_candidates'] = [x for x in candidates if mapping.get(key(x),key(x))==row['category']]
    return rows,notes+parse_notes


def row_queries(row):
    return list(dict.fromkeys(row.get('queries') or [row['query']]))[:4]


def merge_instance_masks(kept, candidate):
    """Deduplicate near-identical detections without growing their silhouettes."""
    import torch
    for index, previous in enumerate(kept):
        if torch.equal(previous, candidate):
            return True
        intersection = (previous.bool() & candidate.bool()).sum().item()
        union = (previous.bool() | candidate.bool()).sum().item()
        if intersection / max(1, union) >= .9:
            return True
    kept.append(candidate)
    return False


def parse_open(text, limit, automatic=True):
    """Accept arbitrary nouns, preserving specific terms instead of urban aliases."""
    raw = lab().clean_inventory(text)
    rows, notes = [], []
    if raw.startswith(('[', '{')):
        legacy = sys.modules[node('DOGMAProposeCategoriesV112').__module__]
        rows, notes = legacy.read_rows(raw)
    else:
        for line in raw.splitlines()[:128]:
            line = re.sub(r'^\s*(?:[-*]|\d+[.)])\s*', '', line).strip()
            if not line or line.upper() in ('NONE', 'NO CATEGORIES'):
                continue
            if line.startswith('|') and line.endswith('|'):
                line = line[1:-1]
            parts = [p.strip() for p in line.split('|')]
            if parts[0].lower() in ('category', 'categories') or re.fullmatch(r'[\s:|\-]+', line):
                continue
            if len(parts) == 2 and all(parts):
                rows.append(dict(category=parts[0], queries=[parts[0]], evidence=parts[1]))
            elif len(parts) == 3 and all(parts):
                rows.append(dict(category=parts[0], queries=[parts[1]], evidence=parts[2]))
            elif len(parts) == 1 and re.fullmatch(r'[A-Za-z][A-Za-z -]{0,49}', parts[0]) and len(parts[0].split()) <= 4:
                rows.append(dict(category=parts[0], queries=[parts[0]], evidence='Location not supplied'))
            else:
                notes.append('Ignored incomplete/unrecognized row: ' + line[:100])
    result, seen, duplicates = [], set(), 0
    for row in rows:
        name = ' '.join(re.sub(r'[^a-zA-Z0-9 -]', ' ', str(row.get('category', ''))).lower().split())
        if not name or len(name) > 60 or name in ('none', 'no categories'):
            continue
        if name in seen:
            duplicates += 1
            notes.append('Merged repeated category: ' + name)
            continue
        queries = row.get('queries')
        query = queries[0] if isinstance(queries, list) and queries and isinstance(queries[0], str) else name
        query = ' '.join(query.split(';')[0].split())[:80] or name
        if automatic:
            if query.lower() != name:
                notes.append('Automatic SAM query uses category name, ignoring auxiliary field: ' + name)
            query = name
        result.append(dict(category=name, query=query, evidence=str(row.get('evidence', ''))[:200]))
        seen.add(name)
    if automatic and duplicates:
        notes.append(f'WARNING: Qwen repeated {duplicates} category rows; merged duplicates. '
                     'Inventory may be incomplete; inspect previews. No extra VLM calls were made.')
    if len(result) > limit:
        notes.append(f'Category budget: {len(result)-limit} proposals omitted; increase max_categories.')
    if not result and raw.upper() not in ('NONE', 'NO CATEGORIES', '[]'):
        raise ValueError('DOGMA: unusable category inventory; no SAM calls made. RAW: ' + raw[:500])
    return result[:limit], list(dict.fromkeys(notes))


class DOGMAPrepPlanV117:
    @classmethod
    def INPUT_TYPES(cls):
        req = dict(image=('IMAGE',), **vlm_settings())
        req.update(mode=(['auto_once', 'manual'],),
                   manual_categories=('STRING', {'multiline': True, 'default': ''}),
                   max_categories=('INT', {'default': 12, 'min': 1, 'max': 24}),
                   planner_side=('INT', {'default': 1024, 'min': 512, 'max': 2048, 'step': 128}),
                   max_tokens=('INT', {'default': 640, 'min': 128, 'max': 2048}),
                   rerun=('INT', {'default': 0, 'min': 0, 'max': 999999}))
        return {'required': req}
    RETURN_TYPES = ('DOGMA_PREP_PLAN', 'STRING')
    RETURN_NAMES = ('plan', 'inventory_and_time')
    FUNCTION = 'run'
    CATEGORY = 'DOGMA/Phase 3 preparation 1.0.21'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return 'full-frame-candidate-accounting-121-v1'

    def run(self, image, model, custom_model_id, memory_mode, mode, manual_categories,
            max_categories, planner_side, max_tokens, rerun):
        started = time.perf_counter()
        lab().interrupted()
        prompt = inventory_prompt(max_categories)
        raw = manual_categories
        draft = ''
        if mode == 'auto_once':
            worker = node('ModernVLM')()
            try:
                draft = worker.run(image=lab().resize_image(image, planner_side), prompt=prompt,
                                 model=model, custom_model_id=custom_model_id, memory_mode=memory_mode,
                                 max_new_tokens=max_tokens, temperature=0., top_p=.9, enable_thinking=False,
                                 unload_after=False, stream_output=True,
                                 system_prompt='You identify major regions in photographs. Return a compact JSON object and stop.')[0]
                raw = worker.run(image=lab().resize_image(image,512),prompt=consolidate_prompt(draft,max_categories),
                                 model=model, custom_model_id=custom_model_id, memory_mode=memory_mode,
                                 max_new_tokens=max_tokens, temperature=0., top_p=.9, enable_thinking=False,
                                 unload_after=False, stream_output=True,
                                 system_prompt='Normalize the supplied visual observation into whole-object targets. Output JSON only.')[0]
            finally:
                worker.clear_model()
        rows, notes = normalized_inventory(draft,raw,max_categories) if mode == 'auto_once' else parse_open(raw, max_categories, automatic=False)
        for index,row in enumerate(rows,1):
            row['target_id'] = f't{index:03d}'
        elapsed = time.perf_counter()-started
        plan = dict(schema=2,rows=rows, seconds=elapsed, raw=raw, visual_draft=draft, notes=notes, mode=mode,
                    vlm_calls=2*int(mode == 'auto_once'), max_categories=max_categories, max_tokens=max_tokens)
        report = f'{len(rows)} dynamic categories; {elapsed:.2f}s including model lifetime; {plan["vlm_calls"]} Qwen call(s).\n'
        report += '\n'.join(f'{i+1}. {r["category"]} -> internal SAM searches: '+', '.join(row_queries(r)) for i,r in enumerate(rows))
        return plan, report+'\nFull-frame objects AND surfaces; every observed candidate accounted for during normalization. Two calls, same worker; no per-mask audits.\n'+'\n'.join(notes)+'\nRAW:\n'+raw+'\nVISUAL DRAFT:\n'+draft


def cards(image, entries):
    """Existing chooser contract, arbitrary number of stable category slots."""
    import torch
    import torch.nn.functional as F
    from PIL import Image, ImageDraw
    import numpy as np
    base = lab().resize_image(image, 640).float().cpu()
    h,w = base.shape[1:3]
    result = []
    for e in entries:
        if not e['active']:
            continue
        union = e['masks'].bool().any(0)[None,None].float()
        mask = F.interpolate(union, size=(h,w), mode='nearest').movedim(1,-1)
        overlay = torch.where(mask.bool(), base*.55+torch.tensor([0.,.85,1.])*.45, base*.6)
        banner = Image.new('RGB', (w*3,36), (28,30,34))
        ImageDraw.Draw(banner).text((8,10),f'{e["slot"]}. {e["name"]} | original / mask / overlay',fill='white')
        title = torch.from_numpy(np.asarray(banner).copy()).float()[None]/255
        result.append(torch.cat([title,torch.cat([base,mask.expand(-1,-1,-1,3),overlay],2)],1))
    return torch.cat(result) if result else torch.zeros((1,64,192,3))


class DOGMAPrepMasksBV117:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': dict(image=('IMAGE',), plan=('DOGMA_PREP_PLAN',),
                model=('MODEL', {'lazy': True}), clip=('CLIP', {'lazy': True}),
                analysis_side=('INT', {'default':1536,'min':512,'max':3072,'step':128}),
                score_threshold=('FLOAT', {'default':.35,'min':.05,'max':.95,'step':.01}),
                max_instances=('INT', {'default':32,'min':1,'max':64}),
                max_mask_coverage=('FLOAT', {'default':.97,'min':.5,'max':1.,'step':.01}),
                min_box_agreement=('FLOAT', {'default':.85,'min':.1,'max':1.,'step':.01}),
                rerun=('INT', {'default':0,'min':0,'max':999999}))}
    RETURN_TYPES = ('DOGMA_CATEGORIES', 'IMAGE', 'STRING')
    RETURN_NAMES = ('categories', 'category_previews', 'mask_timing_and_diagnostics')
    FUNCTION = 'run'
    CATEGORY = DOGMAPrepPlanV117.CATEGORY

    def check_lazy_status(self, plan, model=None, clip=None, **kwargs):
        return [k for k,v in (('model',model),('clip',clip)) if v is None] if plan['rows'] else []

    def run(self, image, plan, analysis_side, score_threshold, max_instances,
            max_mask_coverage, min_box_agreement, rerun, model=None, clip=None):
        import torch
        from nodes import CLIPTextEncode
        if plan.get('schema') != 2 or any(len(row_queries(r)) != 1 for r in plan['rows']):
            raise ValueError('DOGMA: regenerate the inventory with 1.0.21. Each work target requires one independent query.')
        started = time.perf_counter()
        source = lab().resize_image(image, analysis_side)
        h,w = source.shape[1:3]
        entries, stats, encodings = [], [], {}
        shared = 0.
        if plan['rows']:
            with torch.inference_mode():
                for row in plan['rows']:
                    for query in row_queries(row):
                        lab().interrupted()
                        if query in encodings:
                            continue
                        emb,meta = CLIPTextEncode().encode(clip,query)[0][0]
                        if meta.get('sam3_multi_cond'):
                            first = meta['sam3_multi_cond'][0]
                            emb,mask = first['cond'],first.get('attention_mask')
                        else:
                            mask = meta.get('attention_mask')
                        encodings[query] = (emb.detach().cpu(),mask.detach().cpu() if mask is not None else None)
                session = lab().SAMSession(model,encodings)
                try:
                    session.prepare(source)
                    lab().sync()
                    shared = time.perf_counter()-started
                    detections_by_query = {}
                    for slot,row in enumerate(plan['rows'],1):
                        lab().interrupted()
                        tick = time.perf_counter()
                        detected = []
                        kept, reasons = [], []
                        query_counts = []
                        for query in row_queries(row):
                            lab().interrupted()
                            if query not in detections_by_query:
                                detections_by_query[query] = session.detect(query,score_threshold,max_instances,True)
                            found = detections_by_query[query]
                            detected.extend(found)
                            query_counts.append(dict(query=query,detected=len(found)))
                            if len(found) >= max_instances:
                                reasons.append(f'{query}: INSTANCE LIMIT REACHED; additional objects may be missing')
                        for item in detected:
                            ok,why = lab().geometric_check(item['mask'],item['box'],max_mask_coverage,min_box_agreement)
                            if not ok:
                                reasons.append(why)
                                continue
                            if merge_instance_masks(kept,item['mask']):
                                reasons.append('near-identical detection omitted; original silhouette retained')
                        masks = torch.stack(kept).float() if kept else torch.zeros((0,h,w))
                        target_id = row['target_id']
                        entries.append(dict(slot=slot,name=row['category'],query=row['query'],target_id=target_id,
                                            instance_ids=[f'{target_id}:i{i+1:03d}' for i in range(len(kept))],
                                            masks=masks,active=bool(kept)))
                        lab().sync()
                        stats.append(dict(category=row['category'],query=row['query'],queries=query_counts,detected=len(detected),kept=len(kept),
                                          seconds=time.perf_counter()-tick,reasons=reasons))
                finally:
                    session.clear()
        elapsed = time.perf_counter()-started
        report = (f'B: {elapsed:.2f}s including image resize, text/model setup and first image encoding ({shared:.2f}s shared). '
                  f'One SAM image encoding, {len(encodings)} unique text searches across {len(plan["rows"])} independent targets. '
                  f'Analysis {w}x{h}; original {image.shape[2]}x{image.shape[1]}.\n'
                  'Geometry guards are NOT semantic verification. No per-mask Qwen audits or recursive recovery.\n')
        report += '\n'.join(f'{s["category"]}: {s["kept"]}/{s["detected"]} masks; {s["seconds"]:.2f}s; '+ '; '.join(s['reasons']) for s in stats)
        if plan['rows'] and not any(e['active'] for e in entries):
            queries = ', '.join(repr(r['query']) for r in plan['rows'])
            raise ValueError('DOGMA: inventory produced no usable masks; this is not a user selection. '
                             'Check category names and SAM queries before retrying. Queries: ' + queries + '\n' + report)
        bundle = dict(schema=2,entries=entries,shape=tuple(image.shape[1:3]),image=image,plan=plan,mask_stats=stats,mask_seconds=elapsed)
        return bundle,cards(image,entries),report


def assign_ownership(selection, policy):
    import torch
    if selection.get('schema') != 2:
        raise ValueError('DOGMA: old grouped masks cannot be used as independent targets. Regenerate inventory and masks.')
    if policy != 'smaller_regions_first':
        raise ValueError('DOGMA: overlap is disabled in this isolated-target preparation. Select smaller_regions_first.')
    entries = [dict(e,masks=e['masks'].bool().clone()) for e in selection['entries']
               if e['active']]
    notes = []
    if policy == 'smaller_regions_first' and entries:
        occupied = torch.zeros_like(entries[0]['masks'][0])
        ordered = sorted(entries,key=lambda e:(int(e['masks'].any(0).sum()),e['slot']))
        for e in ordered:
            before = int(e['masks'].any(0).sum())
            e['masks'] &= ~occupied
            if bool(e['masks'].any()):
                occupied |= e['masks'].any(0)
            after = int(e['masks'].any(0).sum())
            notes.append(f'{e["name"]}: {before-after} overlap pixels assigned to smaller detected targets (including unselected). Geometry is not semantic verification.')
    for e in entries:
        # Isolate detections within the same type too. Never caption a category union.
        occupied = torch.zeros_like(e['masks'][0])
        for index in sorted(range(len(e['masks'])),key=lambda i:(int(e['masks'][i].sum()),i)):
            e['masks'][index] &= ~occupied
            occupied |= e['masks'][index]
        e['active'] = bool(e['masks'].any())
        e['masks'] = e['masks'].float()
    return [e for e in entries if e['slot'] in set(selection['selected'])],notes


def target_caption_instruction(name):
    return (f'Describe ONLY the visible masked target: {name}. The surrounding scene has been replaced '
            'by an artificial neutral gray background; ignore that background and cutout edges. '
            'Write 35 to 65 words about this target: visible shape, material, color, surface detail and illumination. '
            'Describe a partial view as partial. Do not describe nearby objects, a city scene or the original surroundings. '
            'Do not guess names, history, location, camera, invisible details or the material if unclear. '
            'First decide whether the visible pixels support the requested object type. '
            'If inconsistent, too dark or ambiguous, set matches_target to false; do not invent a plausible description. '
            'Do not describe the artificial cutout shape as the real object shape. Do not infer viewpoint or sunlight. '
            'Return ONLY JSON with "matches_target" (boolean) and "caption" (a factual target description, '
            'or an empty string when uncertain).')


def caption_request(job, day_night):
    lighting = {'night':'Known source context: NIGHT. Do not attribute light to the sun or daylight.',
                'day':'Known source context: DAY. Do not invent the light direction or source.',
                'off':'Do not guess the time of day or source of illumination.'}[day_night]
    return job['caption_instruction']+'\n'+lighting


def parse_target_caption(raw):
    """A review result has no executable edit prompt; malformed output is also review-only."""
    cleaned = lab().clean_inventory(raw)
    try:
        data = json.loads(cleaned)
    except (ValueError,TypeError):
        return '', 'Invalid target-caption JSON; review required.'
    if not isinstance(data,dict) or type(data.get('matches_target')) is not bool:
        return '', 'Missing target assessment; review required.'
    if not data['matches_target']:
        return '', 'Target not confidently recognized in the masked crop; review required.'
    if not isinstance(data.get('caption'),str):
        return '', 'Missing target description; review required.'
    clean = node('DOGMAChunkPromptV566')._declarative(data['caption'])
    if len(clean.split()) < 4:
        return '', 'Unusable target description; review required.'
    return clean, ''


def target_caption_image(job, side):
    """Neutralize all non-target pixels; keep target colors and render input unchanged."""
    import torch
    mask = job['mask'].bool()
    yy,xx = torch.where(mask[0])
    if not len(xx):
        raise ValueError('DOGMA: empty caption target.')
    h,w = mask.shape[-2:]
    x0,x1 = max(0,int(xx.min())-8),min(w,int(xx.max())+9)
    y0,y1 = max(0,int(yy.min())-8),min(h,int(yy.max())+9)
    target = torch.where(mask[...,None].to(job['image'].device),job['image'],.5)
    return lab().resize_image(target[:,y0:y1,x0:x1],side)


class DOGMAPrepCropsV117:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': dict(selection=('DOGMA_CATEGORIES',),
            overlap_policy=(['smaller_regions_first'],),
            target_long_side=('INT',{'default':2048,'min':512,'max':4096,'step':32}),
            group_gap_px=('INT',{'default':180,'min':0,'max':1200}),
            context_px=('INT',{'default':160,'min':32,'max':640,'step':32}),
            max_objects_per_chunk=('INT',{'default':1,'min':1,'max':1}),
            max_chunks_per_category=('INT',{'default':24,'min':1,'max':24}),
            max_total_crops=('INT',{'default':48,'min':1,'max':96}))}
    RETURN_TYPES = ('DOGMA_PREP_CROPS','IMAGE','STRING')
    RETURN_NAMES = ('crop_jobs','selected_masks_after_ownership','crop_geometry_and_time')
    FUNCTION = 'run'
    CATEGORY = DOGMAPrepPlanV117.CATEGORY

    def run(self,selection,overlap_policy,target_long_side,group_gap_px,context_px,
            max_objects_per_chunk,max_chunks_per_category,max_total_crops):
        import math
        import torch
        import torch.nn.functional as F
        started = time.perf_counter()
        entries,notes = assign_ownership(selection,overlap_policy)
        active = [e for e in entries if e['active']]
        jobs, details = [], []
        for index,e in enumerate(active):
            lab().interrupted()
            remaining = max_total_crops-len(jobs)
            if remaining <= 0:
                details.append(f'{e["name"]}: DEFERRED, total crop budget reached; no caption calls.')
                continue
            # Share the bounded workload across remaining selected categories.
            allowance = min(max_chunks_per_category,math.ceil(remaining/(len(active)-index)))
            kind,_,_ = node('DOGMADenoiseCategoryV566')().build(e['name'],'')
            candidates = [i for i,m in enumerate(e['masks']) if bool(m.any())]
            # Stable, largest detections first; budget exhaustion is explicit, never a merge.
            candidates.sort(key=lambda i:(-int(e['masks'][i].sum()),i))
            used = 0
            for position,instance in enumerate(candidates):
                instance_id = e['instance_ids'][instance]
                left = allowance-used
                if left <= 0:
                    details.append(f'{e["name"]} {instance_id}: DEFERRED, crop budget reached.')
                    continue
                instance_budget = max(1,math.ceil(left/(len(candidates)-position)))
                instance_mask = e['masks'][instance:instance+1]
                crops,masks,metadata,info = node('DOGMAObjectNativeCropsV111')().make(
                    selection['image'],instance_mask,e['name'],kind,target_long_side,0,context_px,
                    1,instance_budget,.5)
                details.append(instance_id+': '+info)
                native = F.interpolate(instance_mask[:,None],size=selection['image'].shape[1:3],mode='nearest')[:,0]
                for crop,mask,meta in zip(crops,masks,metadata):
                    if meta.get('noop') or not bool(mask.any()):
                        continue
                    assert crop.shape[1]>=meta['height'] and crop.shape[2]>=meta['width']
                    inp,blend,_,_,_ = node('DOGMADualMaskV566')().build(mask,kind)
                    x,y,w,h = (meta[k] for k in ('x','y','width','height'))
                    pr,pb = meta['pad_right'],meta['pad_bottom']
                    rh,rw = crop.shape[1]-pb,crop.shape[2]-pr
                    support = F.interpolate(native[:,None,y:y+h,x:x+w],size=(rh,rw),mode='nearest')[:,0]
                    support = F.pad(support,(0,pr,0,pb))
                    # Noise support may cross a tile core, never the owning object's silhouette.
                    inp *= support
                    blend *= support
                    meta = dict(meta,target_id=e['target_id'],instance_id=instance_id,query=e['query'],members=1)
                    jobs.append(dict(id=len(jobs)+1,slot=e['slot'],category=e['name'],kind=kind,
                                     target_id=e['target_id'],instance_id=instance_id,query=e['query'],
                                     image=crop,mask=blend,inpaint=inp,metadata=meta,
                                     caption_instruction=target_caption_instruction(e['name'])))
                    used += 1
        elapsed = time.perf_counter()-started
        bundle = dict(schema=2,jobs=jobs,plan=selection['plan'],mask_stats=selection['mask_stats'],
                      mask_seconds=selection['mask_seconds'],crop_seconds=elapsed,geometry=details,ownership=notes,
                      chosen=list(selection['selected']),max_total_crops=max_total_crops)
        report = (f'{len(jobs)} prepared crops; {elapsed:.2f}s. Native source pixels or upscale only. '
                  f'Total crop budget {max_total_crops}; deferred regions are listed below. '
                  'One detection per crop; no category union. Noise and blend confined to the target. '
                  'SAM detections can still contain semantic errors.\n'+'\n'.join(notes+details))
        return bundle,cards(selection['image'],entries),report


def crop_cards(jobs):
    import torch
    import torch.nn.functional as F
    from PIL import Image,ImageDraw
    import numpy as np
    result = []
    for job in jobs:
        base = lab().resize_image(job['image'],384).float().cpu()
        h,w = base.shape[1:3]
        mask = F.interpolate(job['mask'][:,None].float(),size=(h,w),mode='nearest').movedim(1,-1)
        wide = F.interpolate(job['inpaint'][:,None].float(),size=(h,w),mode='nearest').movedim(1,-1)
        overlay = torch.where(mask.bool(),base*.55+torch.tensor([0.,.85,1.])*.45,base*.6)
        cells = []
        for cell in (base,wide.expand(-1,-1,-1,3),mask.expand(-1,-1,-1,3),overlay):
            cells.append(F.pad(cell.movedim(-1,1),(0,384-w,0,384-h)).movedim(1,-1))
        banner = Image.new('RGB',(1536,40),(28,30,34))
        state = 'REVIEW REQUIRED | ' if job.get('review_reason') else ''
        ImageDraw.Draw(banner).text((8,12),f'{job["id"]:03d} {job["category"]} {job["instance_id"]} | {state}crop / inpaint / blend / overlay',fill='white')
        title = torch.from_numpy(np.asarray(banner).copy()).float()[None]/255
        result.append(torch.cat([title,torch.cat(cells,2)],1))
    return torch.cat(result) if result else torch.zeros((1,64,192,3))


class DOGMAPrepDescribeV117:
    @classmethod
    def INPUT_TYPES(cls):
        req = dict(crop_jobs=('DOGMA_PREP_CROPS',), **vlm_settings())
        req.update(caption_side=('INT',{'default':768,'min':384,'max':1536,'step':128}),
                   caption_tokens=('INT',{'default':128,'min':64,'max':512}),
                   day_night=(['day','night','off'],),
                   style=('STRING',{'multiline':True,'default':'A cinematic keyframe from a high-end movie production. Shot on ARRI Alexa. Fine detail with restrained edge contrast, no sharpening halos or crunchy texture.'}),
                   project_context=('STRING',{'multiline':True,'default':'A documentary photograph taken in Italy during the 1970s.'}),
                   save_reports=('BOOLEAN',{'default':True}),
                   rerun=('INT',{'default':0,'min':0,'max':999999}))
        return {'required':req}
    RETURN_TYPES = ('IMAGE','STRING','STRING')
    RETURN_NAMES = ('crop_mask_comparison','all_crop_prompts','timing_and_saved_report')
    FUNCTION = 'run'
    CATEGORY = DOGMAPrepPlanV117.CATEGORY

    def run(self,crop_jobs,model,custom_model_id,memory_mode,caption_side,caption_tokens,
            day_night,style,project_context,save_reports,rerun,_render_payload=False,_trigger=None):
        started = time.perf_counter()
        if crop_jobs.get('schema') != 2:
            raise ValueError('DOGMA: regenerate isolated target crops before captioning.')
        jobs = [dict(j) for j in crop_jobs['jobs']]
        records = []
        if jobs:
            worker = node('ModernVLM')()
            try:
                for job in jobs:
                    lab().interrupted()
                    tick = time.perf_counter()
                    print(f'[DOGMA prep] Caption {job["id"]}/{len(jobs)}: {job["category"]}',flush=True)
                    caption = worker.run(image=target_caption_image(job,caption_side),prompt=caption_request(job,day_night),
                        model=model,custom_model_id=custom_model_id,memory_mode=memory_mode,max_new_tokens=caption_tokens,
                        temperature=0.,top_p=.9,enable_thinking=False,unload_after=False,stream_output=True,
                        system_prompt='Assess and describe only the visible target on the neutral background. Return JSON. Do not invent context.')[0]
                    clean,review_reason = parse_target_caption(caption)
                    job['review_reason'] = review_reason
                    trigger = {'day':'QLCMDAY70','night':'QLCMNIGHT70','off':''}[day_night]
                    if _trigger is not None:trigger=_trigger
                    prompt = '\n\n'.join(x.strip() for x in (trigger,style,project_context,clean) if x.strip()) if not review_reason else ''
                    records.append(dict(id=job['id'],slot=job['slot'],category=job['category'],
                                        target_id=job['target_id'],instance_id=job['instance_id'],query=job['query'],
                                        caption=clean,prompt=prompt,ready=not bool(review_reason),review_reason=review_reason,raw_caption=caption,denoise=job.get('denoise'),
                                        metadata=job['metadata'],render_size=list(job['image'].shape[1:3]),
                                        caption_seconds=time.perf_counter()-tick))
            finally:
                worker.clear_model()
        caption_seconds = time.perf_counter()-started
        total = crop_jobs['plan']['seconds']+crop_jobs['mask_seconds']+crop_jobs['crop_seconds']+caption_seconds
        report = (f'Qwen inventory: {crop_jobs["plan"]["seconds"]:.2f}s\n'
                  f'SAM B including setup: {crop_jobs["mask_seconds"]:.2f}s\n'
                  f'Ownership, native crops and masks: {crop_jobs["crop_seconds"]:.2f}s\n'
                  f'Crop captions including one worker lifetime: {caption_seconds:.2f}s; {len(records)} calls\n'
                  f'Compute subtotal: {total:.2f}s. Excludes user selection wait, cached stages, checkpoint loader, previews and exports.\n'
                  'No diffusion model, CLIP conditioning, VAE encode/decode or sampling in this preparation test.\n'
                  'Planner and captions have separate worker lifetimes. Cached upstream times are retained, not new queue measurements.\n')
        report += f'{sum(r["ready"] for r in records)} ready target prompts; {sum(not r["ready"] for r in records)} require review and have NO edit prompt.\n'
        document = dict(version='1.0.21',inventory=crop_jobs['plan'],mask_stats=crop_jobs['mask_stats'],
                        chosen=crop_jobs['chosen'],geometry=crop_jobs['geometry'],ownership=crop_jobs['ownership'],
                        crop_count=len(records),crop_seconds=crop_jobs['crop_seconds'],mask_seconds=crop_jobs['mask_seconds'],
                        caption_seconds=caption_seconds,compute_subtotal_seconds=total,records=records)
        boards = crop_cards(jobs)
        if save_reports:
            import folder_paths
            dest = Path(folder_paths.get_output_directory())/'DOGMA_PHASE3_PREP'
            dest.mkdir(parents=True,exist_ok=True)
            stem = time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
            target = dest/(stem+'.json')
            target.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
            with (dest/(stem+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['crop','category','instance_id','ready','review_reason','source_x','source_y','source_w','source_h','render_h','render_w','caption_seconds','prompt'])
                for r in records:
                    meta = r['metadata']
                    writer.writerow([r['id'],r['category'],r['instance_id'],r['ready'],r['review_reason'],meta['x'],meta['y'],meta['width'],meta['height'],*r['render_size'],r['caption_seconds'],r['prompt']])
            report += 'Reports saved: '+str(target)+'\n'
        report += f'Caption, preview and export node total: {time.perf_counter()-started:.2f}s'
        prompts = '\n\n--------------------\n\n'.join(f'CROP {r["id"]:03d} — {r["category"]} [{r["instance_id"]}]\n'+(r['prompt'] if r['ready'] else 'DA CONTROLLARE — nessun prompt: '+r['review_reason']) for r in records)
        if _render_payload:
            ready_jobs=[dict(job,**{k:record[k] for k in ('prompt','ready','review_reason','caption')}) for job,record in zip(jobs,records)]
            return dict(crop_jobs,jobs=ready_jobs),boards,prompts or 'No selected crops.',report
        return boards,prompts or 'No selected nonempty crops: no Qwen caption calls.',report


NODE_CLASS_MAPPINGS = {c.__name__:c for c in (DOGMAPrepPlanV117,DOGMAPrepMasksBV117,DOGMAPrepCropsV117,DOGMAPrepDescribeV117)}
NODE_DISPLAY_NAME_MAPPINGS = {k:k.replace('DOGMA','DOGMA ').replace('V117',' 1.0.21') for k in NODE_CLASS_MAPPINGS}
