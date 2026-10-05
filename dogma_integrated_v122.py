"""Phase-3 production integration and optional native Qwen 2.1 prompt enhancer."""
import copy
import json
import math
import re
import time
import uuid
from pathlib import Path
from . import dogma_phase3_prep_v117 as prep
from . import dogma_control_v111 as control

node = prep.node
PE_MODEL = 'qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors'


class DOGMAQwenPromptEnhanceV122:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'prompt': ('STRING', {'multiline': True}),
            'enabled': ('BOOLEAN', {'default': False}),
            'image': ('IMAGE', {'lazy': True}),
            'use_reference': ('BOOLEAN', {'default': False}),
            'reference_instruction': ('STRING', {'multiline': True, 'default': ''}),
            'model_name': ('STRING', {'default': PE_MODEL}),
            'max_tokens': ('INT', {'default': 4096, 'min': 256, 'max': 16384}),
            'seed': ('INT', {'default': 1976, 'min': 0, 'max': 0xffffffffffffffff}),
        }, 'optional': {'reference_image': ('IMAGE',)}}
    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('prompt', 'enhancer_report')
    FUNCTION = 'enhance'
    CATEGORY = 'DOGMA/v1.0.22'

    def check_lazy_status(self, enabled, image=None, use_reference=False, reference_image=None, **kwargs):
        if not enabled:return []
        needed = ['image'] if image is None else []
        return needed

    def enhance(self, prompt, enabled, image, use_reference, reference_instruction,
                model_name, max_tokens, seed, reference_image=None):
        if not enabled:return prompt, 'Prompt enhancer OFF: original prompt unchanged.'
        import folder_paths
        if not folder_paths.get_full_path('text_encoders', model_name):
            raise ValueError('DOGMA: enable the prompt enhancer after downloading '+model_name+' into models/text_encoders, or switch it OFF.')
        active_ref = use_reference and reference_image is not None and reference_image.numel() > 0
        instruction = prompt + ('\n\n'+reference_instruction.strip() if active_ref and reference_instruction.strip() else '')
        images = {'image0': prep.lab().resize_image(image,1024)}
        if active_ref:images['image1'] = prep.lab().resize_image(reference_image,1024)
        batch = node('BatchImagesNode').execute(images=images)[0]
        clip = node('CLIPLoader')().load_clip(model_name, 'qwen_image', 'default')[0]
        generated = node('TextGenerate').execute(
            clip=clip, prompt=instruction, image=batch, max_length=max_tokens,
            sampling_mode=dict(sampling_mode='on',temperature=1.,top_k=20,top_p=.95,
                               min_p=.05,repetition_penalty=1.05,seed=seed,presence_penalty=0.),
            thinking=False,use_default_template=False)[0]
        enhanced = re.sub(r'<think>.*?</think>', '', str(generated), flags=re.S).strip()
        if not enhanced:raise ValueError('DOGMA: prompt enhancer returned no edit instruction; inspect the model or switch it OFF.')
        # Preserve a user-supplied leading LoRA trigger if the rewriter drops it.
        trigger = re.match(r'^([A-Z][A-Z0-9_]{3,})\b', prompt.strip())
        if trigger and trigger[1] not in enhanced:enhanced = trigger[1]+' '+enhanced
        return enhanced, f'Official Qwen 2.1 image-edit PE; {len(images)} image(s); max {max_tokens} tokens. Review the effective prompt before using a new instruction.'


class DOGMAChooseCategoriesV122(control.DOGMAChooseCategoriesV111):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(super().INPUT_TYPES())
        inputs['required']['default_denoise'] = ('FLOAT', {'default': .3, 'min': 0., 'max': 1., 'step': .01})
        return inputs
    CATEGORY = 'DOGMA/v1.0.22'


class DOGMAPhase3CropsV122(prep.DOGMAPrepCropsV117):
    CATEGORY = 'DOGMA/v1.0.22'
    def run(self, selection, **kwargs):
        bundle, cards, report = super().run(selection, **kwargs)
        values = selection['denoise_by_target']
        for job in bundle['jobs']:
            job['denoise'] = values[job['target_id']]
        bundle['image'] = selection['image']
        bundle['denoise_by_target'] = dict(values)
        return bundle, cards, report


class DOGMAPhase3DescribeV122(prep.DOGMAPrepDescribeV117):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(super().INPUT_TYPES())
        inputs['required'].pop('day_night')
        inputs['required'].update(night=('BOOLEAN', {'default': True}),
            look_enabled=('BOOLEAN', {'default': True}),
            day_trigger=('STRING', {'default': 'QLCMDAY70'}),
            night_trigger=('STRING', {'default': 'QLCMNIGHT70'}))
        return inputs
    RETURN_TYPES = ('DOGMA_RENDER_JOBS','IMAGE','STRING','STRING')
    RETURN_NAMES = ('render_jobs','crop_mask_comparison','all_crop_prompts','preparation_report')
    CATEGORY = 'DOGMA/v1.0.22'
    def run(self, night, look_enabled, day_trigger, night_trigger, **kwargs):
        trigger = (night_trigger if night else day_trigger) if look_enabled else ''
        return super().run(day_night='night' if night else 'day', _trigger=trigger,
                           _render_payload=True, **kwargs)


def renderable(job):
    return bool(job.get('ready') and job.get('prompt') and job['denoise'] > 0)


class DOGMAPhase3RenderV122:
    @classmethod
    def INPUT_TYPES(cls):
        import comfy.samplers
        return {'required': {
            'prepared': ('DOGMA_RENDER_JOBS',),
            **{k:(t,{'lazy':True}) for k,t in [('model','MODEL'),('clip','CLIP'),('vae','VAE'),('sampler','SAMPLER')]},
            'negative_prompt': ('STRING', {'multiline': True, 'default': ''}),
            'steps': ('INT', {'default': 12, 'min': 1, 'max': 10000}),
            'cfg': ('FLOAT', {'default': 1., 'min': 0., 'max': 100., 'step': .1}),
            'scheduler': (comfy.samplers.SCHEDULER_NAMES,),
            'seed': ('INT', {'default': 1976, 'min': 0, 'max': 0xffffffffffffffff}),
            'vae_tile_size': ('INT', {'default': 1024, 'min': 512, 'max': 4096, 'step': 64}),
            'vae_overlap': ('INT', {'default': 128, 'min': 64, 'max': 512, 'step': 32}),
            'low_frequency_strength': ('FLOAT', {'default': .15, 'min': 0., 'max': 1., 'step': .05}),
            'save_reports': ('BOOLEAN', {'default': True}),
        }}
    RETURN_TYPES = ('IMAGE','STRING')
    RETURN_NAMES = ('image','render_report')
    FUNCTION = 'render'
    CATEGORY = 'DOGMA/v1.0.22'

    def check_lazy_status(self, prepared, **kwargs):
        if not any(renderable(j) for j in prepared['jobs']):return []
        return [k for k in ('model','clip','vae','sampler') if kwargs.get(k) is None]

    def render(self, prepared, negative_prompt, steps, cfg, scheduler, seed, vae_tile_size,
               vae_overlap, low_frequency_strength, save_reports,
               model=None, clip=None, vae=None, sampler=None):
        if prepared.get('schema') != 2:raise ValueError('DOGMA: regenerate isolated target jobs.')
        started = time.perf_counter()
        result = prepared['image']
        jobs = prepared['jobs']
        if any(not math.isfinite(j['denoise']) or not 0 <= j['denoise'] <= 1 for j in jobs):
            raise ValueError('DOGMA: invalid per-category denoise.')
        report=[];negative=None;sigmas_by_denoise={}
        for job in jobs:
            prep.lab().interrupted()
            info=dict(id=job['id'],category=job['category'],target_id=job['target_id'],instance_id=job['instance_id'],denoise=job['denoise'])
            if not renderable(job):
                info.update(status='preserved',reason=job.get('review_reason') or 'denoise=0')
                report.append(info);continue
            d=job['denoise']
            if d not in sigmas_by_denoise:
                sigmas_by_denoise[d]=node('BasicScheduler')().get_sigmas(model,scheduler,steps,d)[0]
            positive=node('CLIPTextEncode')().encode(clip,job['prompt'])[0]
            if negative is None:negative=node('CLIPTextEncode')().encode(clip,negative_prompt)[0]
            positive,neg,latent=node('DOGMAMaskedDenoiseLatentV566')().encode(
                positive,negative,vae,job['image'],job['inpaint'],True,vae_tile_size,vae_overlap)
            noise_seed=(seed+job['id']-1) & 0xffffffffffffffff
            print(f'[DOGMA render] {job["id"]}/{len(jobs)} {job["category"]}: denoise={d:.2f}',flush=True)
            sampled=node('SamplerCustom')().sample(model,True,noise_seed,cfg,positive,neg,sampler,sigmas_by_denoise[d],latent)[0]
            patch=node('VAEDecodeTiled')().decode(vae,sampled,vae_tile_size,vae_overlap)[0]
            result,_=node('DOGMASoftStitchV566')().stitch_regions(
                result,[patch],[job['inpaint']],[job['mask']],[job['metadata']],job['category'],job['kind'],low_frequency_strength)
            info.update(status='rendered',seed=noise_seed,prompt=job['prompt'])
            report.append(info)
        document=dict(version='1.0.22',steps=steps,cfg=cfg,scheduler=scheduler,base_seed=seed,
                      elapsed_seconds=time.perf_counter()-started,jobs=report)
        summary='\n'.join(f'{r["id"]:03d} {r["category"]}: {r["status"]}; denoise {r["denoise"]:.2f}'+(' — '+r['reason'] if 'reason' in r else '') for r in report)
        if save_reports:
            import folder_paths
            dest=Path(folder_paths.get_output_directory())/'DOGMA_PHASE3_RENDER'
            dest.mkdir(parents=True,exist_ok=True)
            path=dest/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.json')
            path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
            summary+='\nReport: '+str(path)
        return result, summary or 'No selected render jobs: original image preserved.'


NODE_CLASS_MAPPINGS={c.__name__:c for c in (DOGMAQwenPromptEnhanceV122,DOGMAChooseCategoriesV122,DOGMAPhase3CropsV122,DOGMAPhase3DescribeV122,DOGMAPhase3RenderV122)}
NODE_DISPLAY_NAME_MAPPINGS={k:k.replace('DOGMA','DOGMA ').replace('V122',' 1.0.22') for k in NODE_CLASS_MAPPINGS}
