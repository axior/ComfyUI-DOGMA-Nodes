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
    return (f'List at most {limit} different types of visible objects and surfaces in this image. '
            'Use short English names. Look across the whole image, including foreground and background. '
            'Include the ground surface when visible. Name complete objects rather than their parts. '
            'Write each type only once, one name per line. '
            'Do not write locations, descriptions, tables, or explanations. '
            'Do not guess objects that are not visible. Write NONE if nothing is identifiable.')


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
                   max_tokens=('INT', {'default': 192, 'min': 128, 'max': 1024}),
                   rerun=('INT', {'default': 0, 'min': 0, 'max': 999999}))
        return {'required': req}
    RETURN_TYPES = ('DOGMA_PREP_PLAN', 'STRING')
    RETURN_NAMES = ('plan', 'inventory_and_time')
    FUNCTION = 'run'
    CATEGORY = 'DOGMA/Phase 3 preparation 1.0.18'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return 'open-noun-inventory-118-v1'

    def run(self, image, model, custom_model_id, memory_mode, mode, manual_categories,
            max_categories, planner_side, max_tokens, rerun):
        started = time.perf_counter()
        lab().interrupted()
        prompt = inventory_prompt(max_categories)
        raw = manual_categories
        if mode == 'auto_once':
            worker = node('ModernVLM')()
            try:
                raw = worker.run(image=lab().resize_image(image, planner_side), prompt=prompt,
                                 model=model, custom_model_id=custom_model_id, memory_mode=memory_mode,
                                 max_new_tokens=max_tokens, temperature=0., top_p=.9, enable_thinking=False,
                                 unload_after=False, stream_output=True, system_prompt='Return only the requested short inventory.')[0]
            finally:
                worker.clear_model()
        rows, notes = parse_open(raw, max_categories, automatic=mode == 'auto_once')
        elapsed = time.perf_counter()-started
        plan = dict(rows=rows, seconds=elapsed, raw=raw, notes=notes, mode=mode,
                    vlm_calls=int(mode == 'auto_once'), max_categories=max_categories, max_tokens=max_tokens)
        report = f'{len(rows)} dynamic categories; {elapsed:.2f}s including model lifetime; {plan["vlm_calls"]} Qwen call(s).\n'
        report += '\n'.join(f'{i+1}. {r["category"]} -> SAM: {r["query"]} | {r["evidence"]}' for i,r in enumerate(rows))
        return plan, report+'\n'+'\n'.join(notes)+'\nRAW:\n'+raw


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
        started = time.perf_counter()
        source = lab().resize_image(image, analysis_side)
        h,w = source.shape[1:3]
        entries, stats, encodings = [], [], {}
        shared = 0.
        if plan['rows']:
            with torch.inference_mode():
                for row in plan['rows']:
                    lab().interrupted()
                    query = row['query']
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
                    for slot,row in enumerate(plan['rows'],1):
                        lab().interrupted()
                        tick = time.perf_counter()
                        detected = session.detect(row['query'],score_threshold,max_instances,True)
                        kept, reasons = [], []
                        for item in detected:
                            ok,why = lab().geometric_check(item['mask'],item['box'],max_mask_coverage,min_box_agreement)
                            if not ok:
                                reasons.append(why)
                                continue
                            # Exact duplicate masks do not create duplicate crop jobs.
                            if any(torch.equal(item['mask'],other) for other in kept):
                                reasons.append('duplicate instance mask')
                                continue
                            kept.append(item['mask'])
                        masks = torch.stack(kept).float() if kept else torch.zeros((0,h,w))
                        entries.append(dict(slot=slot,name=row['category'],query=row['query'],masks=masks,active=bool(kept)))
                        if len(detected) >= max_instances:
                            reasons.append('INSTANCE LIMIT REACHED; additional objects may be missing')
                        lab().sync()
                        stats.append(dict(category=row['category'],query=row['query'],detected=len(detected),kept=len(kept),
                                          seconds=time.perf_counter()-tick,reasons=reasons))
                finally:
                    session.clear()
        elapsed = time.perf_counter()-started
        report = (f'B: {elapsed:.2f}s including image resize, text/model setup and first image encoding ({shared:.2f}s shared). '
                  f'One SAM image encoding, {len(plan["rows"])} text searches when inventory is nonempty. '
                  f'Analysis {w}x{h}; original {image.shape[2]}x{image.shape[1]}.\n'
                  'Geometry guards are NOT semantic verification. No per-mask Qwen audits or recursive recovery.\n')
        report += '\n'.join(f'{s["category"]}: {s["kept"]}/{s["detected"]} masks; {s["seconds"]:.2f}s; '+ '; '.join(s['reasons']) for s in stats)
        if plan['rows'] and not any(e['active'] for e in entries):
            queries = ', '.join(repr(r['query']) for r in plan['rows'])
            raise ValueError('DOGMA: inventory produced no usable masks; this is not a user selection. '
                             'Check category names and SAM queries before retrying. Queries: ' + queries + '\n' + report)
        bundle = dict(entries=entries,shape=tuple(image.shape[1:3]),image=image,plan=plan,mask_stats=stats,mask_seconds=elapsed)
        return bundle,cards(image,entries),report


def assign_ownership(selection, policy):
    import torch
    entries = [dict(e,masks=e['masks'].bool().clone()) for e in selection['entries']
               if e['active'] and e['slot'] in set(selection['selected'])]
    notes = []
    if policy == 'smaller_regions_first' and entries:
        occupied = torch.zeros_like(entries[0]['masks'][0])
        ordered = sorted(entries,key=lambda e:(int(e['masks'].any(0).sum()),e['slot']))
        for e in ordered:
            before = int(e['masks'].any(0).sum())
            e['masks'] &= ~occupied
            e['masks'] = e['masks'][e['masks'].flatten(1).any(1)]
            if len(e['masks']):
                occupied |= e['masks'].any(0)
            after = int(e['masks'].any(0).sum()) if len(e['masks']) else 0
            notes.append(f'{e["name"]}: {before-after} overlap pixels assigned to smaller selected categories.')
    for e in entries:
        e['active'] = bool(len(e['masks']))
        e['masks'] = e['masks'].float()
    return entries,notes


class DOGMAPrepCropsV117:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': dict(selection=('DOGMA_CATEGORIES',),
            overlap_policy=(['smaller_regions_first','allow_overlap'],),
            target_long_side=('INT',{'default':2048,'min':512,'max':4096,'step':32}),
            group_gap_px=('INT',{'default':180,'min':0,'max':1200}),
            context_px=('INT',{'default':160,'min':32,'max':640,'step':32}),
            max_objects_per_chunk=('INT',{'default':6,'min':1,'max':20}),
            max_chunks_per_category=('INT',{'default':12,'min':1,'max':24}),
            max_total_crops=('INT',{'default':24,'min':1,'max':96}))}
    RETURN_TYPES = ('DOGMA_PREP_CROPS','IMAGE','STRING')
    RETURN_NAMES = ('crop_jobs','selected_masks_after_ownership','crop_geometry_and_time')
    FUNCTION = 'run'
    CATEGORY = DOGMAPrepPlanV117.CATEGORY

    def run(self,selection,overlap_policy,target_long_side,group_gap_px,context_px,
            max_objects_per_chunk,max_chunks_per_category,max_total_crops):
        import math
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
            kind,instruction,_ = node('DOGMADenoiseCategoryV566')().build(e['name'],'')
            crops,masks,metadata,info = node('DOGMAObjectNativeCropsV111')().make(
                selection['image'],e['masks'],e['name'],kind,target_long_side,group_gap_px,context_px,
                max_objects_per_chunk,allowance,.5)
            details.append(info)
            for crop,mask,meta in zip(crops,masks,metadata):
                if meta.get('noop') or not bool(mask.any()):
                    continue
                assert crop.shape[1]>=meta['height'] and crop.shape[2]>=meta['width']
                inp,blend,_,_,_ = node('DOGMADualMaskV566')().build(mask,kind)
                jobs.append(dict(id=len(jobs)+1,slot=e['slot'],category=e['name'],kind=kind,
                                 image=crop,mask=blend,inpaint=inp,metadata=meta,caption_instruction=instruction))
        elapsed = time.perf_counter()-started
        bundle = dict(jobs=jobs,plan=selection['plan'],mask_stats=selection['mask_stats'],
                      mask_seconds=selection['mask_seconds'],crop_seconds=elapsed,geometry=details,ownership=notes,
                      chosen=list(selection['selected']),max_total_crops=max_total_crops)
        report = (f'{len(jobs)} prepared crops; {elapsed:.2f}s. Native source pixels or upscale only. '
                  f'Total crop budget {max_total_crops}; deferred regions are listed below.\n'+'\n'.join(notes+details))
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
        ImageDraw.Draw(banner).text((8,12),f'{job["id"]:03d} {job["category"]} | crop / inpaint / blend / overlay',fill='white')
        title = torch.from_numpy(np.asarray(banner).copy()).float()[None]/255
        result.append(torch.cat([title,torch.cat(cells,2)],1))
    return torch.cat(result) if result else torch.zeros((1,64,192,3))


class DOGMAPrepDescribeV117:
    @classmethod
    def INPUT_TYPES(cls):
        req = dict(crop_jobs=('DOGMA_PREP_CROPS',), **vlm_settings())
        req.update(caption_side=('INT',{'default':768,'min':384,'max':1536,'step':128}),
                   caption_tokens=('INT',{'default':192,'min':64,'max':512}),
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
            day_night,style,project_context,save_reports,rerun):
        started = time.perf_counter()
        jobs = crop_jobs['jobs']
        records = []
        if jobs:
            worker = node('ModernVLM')()
            try:
                for job in jobs:
                    lab().interrupted()
                    tick = time.perf_counter()
                    print(f'[DOGMA prep] Caption {job["id"]}/{len(jobs)}: {job["category"]}',flush=True)
                    caption = worker.run(image=lab().resize_image(job['image'],caption_side),prompt=job['caption_instruction'],
                        model=model,custom_model_id=custom_model_id,memory_mode=memory_mode,max_new_tokens=caption_tokens,
                        temperature=0.,top_p=.9,enable_thinking=False,unload_after=False,stream_output=True,
                        system_prompt='Describe only the supplied crop. Do not invent objects, historical dates or camera settings.')[0]
                    clean = node('DOGMAChunkPromptV566')._declarative(caption)
                    if len(clean.split())<4:
                        raise ValueError(f'DOGMA: unusable caption for crop {job["id"]}; no fabricated fallback prompt.')
                    trigger = {'day':'QLCMDAY70','night':'QLCMNIGHT70','off':''}[day_night]
                    prompt = '\n\n'.join(x.strip() for x in (trigger,style,project_context,clean) if x.strip())
                    records.append(dict(id=job['id'],slot=job['slot'],category=job['category'],caption=clean,prompt=prompt,
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
        document = dict(version='1.0.17',inventory=crop_jobs['plan'],mask_stats=crop_jobs['mask_stats'],
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
                writer.writerow(['crop','category','source_x','source_y','source_w','source_h','render_h','render_w','caption_seconds','prompt'])
                for r in records:
                    meta = r['metadata']
                    writer.writerow([r['id'],r['category'],meta['x'],meta['y'],meta['width'],meta['height'],*r['render_size'],r['caption_seconds'],r['prompt']])
            report += 'Reports saved: '+str(target)+'\n'
        report += f'Caption, preview and export node total: {time.perf_counter()-started:.2f}s'
        prompts = '\n\n--------------------\n\n'.join(f'CROP {r["id"]:03d} — {r["category"]}\n{r["prompt"]}' for r in records)
        return boards,prompts or 'No selected nonempty crops: no Qwen caption calls.',report


NODE_CLASS_MAPPINGS = {c.__name__:c for c in (DOGMAPrepPlanV117,DOGMAPrepMasksBV117,DOGMAPrepCropsV117,DOGMAPrepDescribeV117)}
NODE_DISPLAY_NAME_MAPPINGS = {k:k.replace('DOGMA','DOGMA ').replace('V117',' 1.0.17') for k in NODE_CLASS_MAPPINGS}
