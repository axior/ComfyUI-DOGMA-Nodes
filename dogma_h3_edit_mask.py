"""User-supplied video masks, spatial adjustments and bounded edit compositing."""
import asyncio
import hashlib
import inspect
import json
import math
from pathlib import Path
import threading
import uuid
from fractions import Fraction

import av
import numpy as np
from scipy.ndimage import maximum_filter, minimum_filter, gaussian_filter


def mask_defaults():
    return dict(enabled=False, source='', grow=0, feather=0., opacity=.55, view='overlay')


def mask_settings(value):
    settings = {**mask_defaults(), **(value or {})}
    if not settings['enabled']:
        return settings
    grow, feather, opacity = (float(settings[k]) for k in ('grow', 'feather', 'opacity'))
    if not all(math.isfinite(x) for x in (grow, feather, opacity)) or feather < 0 or not 0 <= opacity <= 1:
        raise ValueError('Regolazioni maschera non valide: sfumatura positiva e opacità da 0 a 1.')
    settings.update(grow=round(grow), feather=feather, opacity=opacity)
    if settings['view'] not in ('overlay', 'mask', 'source'):
        raise ValueError('Vista maschera non valida.')
    return settings


def validate_alignment(source, mask):
    if (source['width'], source['height']) != (mask['width'], mask['height']):
        raise ValueError('La maschera deve avere le stesse dimensioni del video originale.')
    a, b = source['frame_times'], mask['frame_times']
    tolerance = max(.001, .25/source['fps'])
    if len(a) != len(b) or abs(source['duration']-mask['duration']) > tolerance or any(abs(x-y) > tolerance for x,y in zip(a,b)):
        raise ValueError('La maschera deve coprire tutto il sorgente con gli stessi fotogrammi e tempi.')


def processed_mask(rgb, settings):
    alpha = (rgb.astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32))/255.
    alpha[alpha < 1/255] = 0
    alpha[alpha > 254/255] = 1
    grow = settings['grow']
    if grow:
        fn = maximum_filter if grow > 0 else minimum_filter
        alpha = fn(alpha, size=2*abs(grow)+1, mode='constant', cval=0)
    if settings['feather']:
        alpha = gaussian_filter(alpha, sigma=settings['feather'], mode='constant', cval=0)
    return np.clip(alpha, 0, 1)


def fade_weight(second, plan, fade, frame_duration):
    fade = min(float(fade), plan['duration']/2)
    if fade <= 0 or plan['source_frames'] <= 1:
        return 1.
    return max(0., min(1., (second-plan['start']+frame_duration)/fade, (plan['end']-second)/fade))


class FrameReader:
    def __init__(self, path, start=0):
        self.container = av.open(str(path))
        self.stream = self.container.streams.video[0]
        self.origin = float(self.stream.start_time*self.stream.time_base) if self.stream.start_time is not None else 0.
        self.container.seek(int((self.origin+start)/float(self.stream.time_base)), stream=self.stream, backward=True)
        self.frames = self.container.decode(self.stream)
        self.current = next(self.frames, None)
        self.following = next(self.frames, None)
        if self.current is None:
            self.close()
            raise ValueError('Video privo di fotogrammi leggibili.')

    def at(self, second):
        while self.following is not None and float(self.following.time)-self.origin <= second+1e-6:
            self.current = self.following
            self.following = next(self.frames, None)
        return self.current.to_ndarray(format='rgb24')

    def close(self):
        self.container.close()


def resize_rgb(rgb, size):
    if (rgb.shape[1], rgb.shape[0]) == size:
        return rgb
    return av.VideoFrame.from_ndarray(rgb, format='rgb24').reformat(width=size[0], height=size[1]).to_ndarray(format='rgb24')


def resize_alpha(alpha, size):
    if (alpha.shape[1], alpha.shape[0]) == size:
        return alpha
    from PIL import Image
    return np.asarray(Image.fromarray(alpha).resize(size, Image.Resampling.BILINEAR), dtype=np.float32)


def prepare_masked_latent(director, latent, vae, selected, mask_path, settings, plan, content_size, interrupt):
    import torch
    import nodes
    from comfy.nested_tensor import NestedTensor
    # Native per-row masking must be available; do not patch the global model.
    try:
        from comfy.ldm.minimax.model import mask_row_values
    except ImportError:
        raise ValueError('Aggiorna ComfyUI: il masking nativo H3 richiesto non è disponibile.') from None
    node = nodes.NODE_CLASS_MAPPINGS.get('MVEx_MaskToLatentSpace')
    if node is None:
        raise ValueError('La maschera H3 richiede MaskVidExperiments aggiornato dal Manager.')
    empty_video, audio = latent['samples'].unbind()
    width, height = selected.shape[2], selected.shape[1]
    masks = torch.empty((len(selected),height,width),dtype=torch.float32)
    reader = FrameReader(mask_path,plan['start'])
    try:
        for i in range(len(selected)):
            interrupt()
            second = min(plan['start']+i/24,plan['last_source_time'])
            alpha = resize_alpha(processed_mask(reader.at(second),settings),content_size)
            alpha = np.pad(alpha,((0,height-alpha.shape[0]),(0,width-alpha.shape[1])),mode='constant')
            masks[i] = torch.from_numpy(alpha)
    finally:
        reader.close()
    kwargs = dict(masks=masks,compression={'compression':'auto'},spatial_method='max',temporal_method='max',
                  grow_spatial=0,grow_temporal=0,vae=vae)
    # This input was added by MaskVidExperiments after the version in this install.
    if 'grow_temp_mode' in inspect.signature(node.execute).parameters:
        kwargs['grow_temp_mode'] = 'both'
    reduced = director.call('MVEx_MaskToLatentSpace',**kwargs)[0]
    plate = vae.encode(selected[:,:,:,:3])
    if tuple(plate.shape) != tuple(empty_video.shape) or tuple(reduced.shape) != tuple(plate.shape[-3:]):
        raise ValueError('Video, maschera e griglia temporale H3 non coincidono. Aggiorna ComfyUI e MaskVidExperiments.')
    result = latent.copy()
    result['samples'] = NestedTensor((plate,audio))
    result['noise_mask'] = NestedTensor((reduced[None,None].to(dtype=plate.dtype),torch.zeros_like(audio)))
    return result


def inspect_native_mask(latent):
    """Validate the actual AV mask handed to sampling, not only the preview."""
    import torch
    mask=latent.get('noise_mask')
    if mask is None or not getattr(mask,'is_nested',hasattr(mask,'unbind')):
        raise ValueError('Maschera edit assente dai latenti: campionamento annullato.')
    try:
        video,audio=latent['samples'].unbind();vm,am=mask.unbind()
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Maschera edit AV non valida.') from None
    if vm.ndim!=video.ndim or vm.shape[0]!=video.shape[0] or vm.shape[1] not in (1,video.shape[1]) or tuple(vm.shape[2:])!=tuple(video.shape[2:]):
        raise ValueError('La maschera non coincide con la griglia video del campionamento.')
    if tuple(am.shape)!=tuple(audio.shape) or not torch.isfinite(am).all() or torch.count_nonzero(am):
        raise ValueError('La maschera audio deve restare a zero durante l’edit.')
    if not torch.isfinite(vm).all() or vm.min()<0 or vm.max()>1:
        raise ValueError('La maschera video contiene valori non validi.')
    if not torch.count_nonzero(vm):raise ValueError('La selezione non contiene aree bianche nella maschera: nessun edit da applicare.')
    return dict(enabled=True,shape=list(vm.shape),coverage=round(float(vm.float().mean()),6),audio_locked=True)

def write_segment(source, generated, dest, meta, plan, *, mask_path=None, settings=None,
                  size=None, fade=0., preview=False, precomposited=False, interrupt=lambda:None, progress=lambda a,b:None):
    """Only the selected interval is decoded; mask adjustments use source pixels."""
    size = size or (meta['width'], meta['height'])
    readers = []
    try:
        src = FrameReader(source, plan['start']); readers.append(src)
        gen = FrameReader(generated) if generated else None
        if gen: readers.append(gen)
        mask = FrameReader(mask_path, plan['start']) if mask_path else None
        if mask: readers.append(mask)
        times = meta['frame_times'][plan['start_frame']:plan['end_frame']]
        with av.open(str(dest), 'w') as out:
            codec = 'libx264' if preview else 'ffv1'
            stream = out.add_stream(codec, rate=Fraction(meta['fps_ratio']))
            stream.width, stream.height = size
            stream.pix_fmt = 'yuv420p' if preview else 'bgr0'
            stream.time_base = Fraction(1, 1000000)
            if preview: stream.options = {'crf':'18', 'preset':'veryfast'}
            for i, second in enumerate(times):
                interrupt()
                original = resize_rgb(src.at(second), size)
                alpha = processed_mask(mask.at(second), settings) if mask else np.ones((size[1],size[0]),np.float32)
                next_time = times[i+1] if i+1 < len(times) else plan['end']
                alpha = resize_alpha(alpha, size)*fade_weight(second, plan, fade, next_time-second)
                # An approved trial already includes feather and temporal fades.
                # Applying their alpha twice would bring the old wall back.
                if precomposited:alpha=(alpha>0).astype(np.float32)
                if preview:
                    if settings['view'] == 'mask':
                        rgb = np.repeat(np.rint(alpha[...,None]*255).astype(np.uint8), 3, axis=2)
                    elif settings['view'] == 'source':
                        rgb = original
                    else:
                        mix = alpha[...,None]*settings['opacity']
                        rgb = np.rint(original*(1-mix)+np.array([255,80,35])*mix).astype(np.uint8)
                else:
                    replacement = resize_rgb(gen.at(second-plan['start']), size)
                    mix = alpha[...,None]
                    rgb = np.rint(original*(1-mix)+replacement*mix).clip(0,255).astype(np.uint8)
                frame = av.VideoFrame.from_ndarray(rgb, format='rgb24')
                frame.pts = round((second-plan['start'])*1000000)
                frame.time_base = Fraction(1,1000000)
                for packet in stream.encode(frame): out.mux(packet)
                progress(i+1,len(times))
            for packet in stream.encode(): out.mux(packet)
    except BaseException:
        Path(dest).unlink(missing_ok=True)
        raise
    finally:
        for reader in readers: reader.close()


def register_mask_routes(routes, input_file, probe, plan_interval):
    from aiohttp import web
    import folder_paths
    jobs = {}
    slot = asyncio.Semaphore(1)

    def describe(data):
        settings = mask_settings(data.get('mask'))
        source, mask = input_file(data['source']), input_file(settings['source'])
        meta, mask_meta = probe(source), probe(mask)
        validate_alignment(meta, mask_meta)
        plan = plan_interval(meta,data['start'],data['end'])
        fade = float(data.get('fade',0))
        if not math.isfinite(fade) or not 0 <= fade <= .5:
            raise ValueError('Raccordo maschera non valido.')
        stamps = [(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in (source,mask)]
        key = hashlib.sha256(json.dumps([stamps,settings,plan,fade],sort_keys=True).encode()).hexdigest()
        return source,mask,meta,plan,settings,fade,key

    async def work(job, data):
        try:
            async with slot:
                if job['cancel'].is_set(): job['status']='cancelled';return
                source,mask,meta,plan,settings,fade,key = await asyncio.to_thread(describe,data)
                directory = Path(folder_paths.get_temp_directory())/'DOGMA_MASK_PREVIEW'
                directory.mkdir(parents=True,exist_ok=True)
                dest = directory/(key+'.mp4')
                job['status'] = 'running'
                if not dest.is_file():
                    scale = min(1.,960/max(meta['width'],meta['height']))
                    size = tuple(max(2,round(x*scale/2)*2) for x in (meta['width'],meta['height']))
                    def interrupt():
                        if job['cancel'].is_set(): raise InterruptedError('Anteprima annullata.')
                    def progress(done,total): job.update(done=done,total=total)
                    temp = directory/(key+'.'+job['id']+'.mp4')
                    await asyncio.to_thread(write_segment,source,None,temp,meta,plan,mask_path=mask,settings=settings,
                                            size=size,fade=fade,preview=True,interrupt=interrupt,progress=progress)
                    temp.replace(dest)
                job.update(status='done',file={'filename':dest.name,'subfolder':'DOGMA_MASK_PREVIEW','type':'temp'},
                           selection=plan,settings=settings)
        except InterruptedError:
            job['status'] = 'cancelled'
        except Exception as exc:
            job.update(status='error',message=str(exc))

    @routes.post('/dogma/h3/v2/edit/mask-preview')
    async def start_preview(request):
        data = await request.json()
        # Bound completed job records; video files live in Comfy's temporary folder.
        for key in list(jobs):
            if len(jobs)<32: break
            if jobs[key]['status'] in ('done','error','cancelled'): jobs.pop(key)
        if len(jobs)>=32: raise web.HTTPTooManyRequests(text='Attendi le anteprime già in corso.')
        uid = uuid.uuid4().hex
        job = {'id':uid,'status':'queued','done':0,'total':0,'cancel':threading.Event()}
        jobs[uid] = job
        job['task'] = asyncio.create_task(work(job,data))
        return web.json_response({'id':uid,'status':'queued'})

    @routes.get('/dogma/h3/v2/edit/mask-preview/{id}')
    async def preview_status(request):
        job = jobs.get(request.match_info['id'])
        if not job: raise web.HTTPNotFound(text='Anteprima non disponibile.')
        return web.json_response({k:v for k,v in job.items() if k not in ('cancel','task')})

    @routes.delete('/dogma/h3/v2/edit/mask-preview/{id}')
    async def cancel_preview(request):
        job = jobs.get(request.match_info['id'])
        if job: job['cancel'].set()
        return web.json_response({'ok':True})

    async def cleanup(app):
        for job in jobs.values(): job['cancel'].set()
        await asyncio.gather(*(j['task'] for j in jobs.values()),return_exceptions=True)
    # The server owns task lifetime; cancellation is also available per preview.
    return cleanup
