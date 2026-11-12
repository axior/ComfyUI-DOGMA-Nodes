"""Bounded H3 Ref2VA edits and a streaming, timestamp-preserving full-video export.

No model downloads, no upscale, no full source video in a tensor.
"""
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from fractions import Fraction

# Official output range 4–15 s, intersected with Comfy's 17k+5 grid.
# 362/24 exceeds the 15 s reference budget; keep the source reference <=15 s.
EDIT_FRAMES = tuple(range(107, 346, 17))


def edit_defaults():
    return dict(source='', start=0., end=107/24, fade=.125, anchor_edges=True,
                turbo='', turbo_strength=1., steps=20, sampler='res_multistep',
                scheduler='simple', shift_video=12., shift_audio=3.,
                lying=0., lying_start=.1, lying_end=.9)


def ffmpeg():
    executable = shutil.which('ffmpeg')
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            pass
    if not executable or not Path(executable).is_file():
        raise ValueError('Video Edit richiede FFmpeg (oppure imageio-ffmpeg) sul computer Comfy.')
    return executable


def probe(path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('Il file non contiene una traccia video.')
        s = container.streams.video[0]
        rate = s.average_rate or s.guessed_rate
        if not rate or rate <= 0:
            raise ValueError('FPS del sorgente non leggibili.')
        duration = float(s.duration * s.time_base) if s.duration else float((container.duration or 0)/av.time_base)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Durata del video non leggibile.')
        # Reject formats that need a separate color-managed / orientation workflow.
        rotation = int(float(s.metadata.get('rotate', '0'))) % 360
        first = next(container.decode(s), None)
        if first is None:
            raise ValueError('Video privo di fotogrammi decodificabili.')
        rotation = int(getattr(first, 'rotation', rotation) or rotation) % 360
        if rotation:
            raise ValueError('Video con rotazione metadata: esportalo con rotazione applicata prima di editarlo.')
        if s.sample_aspect_ratio and s.sample_aspect_ratio != 1:
            raise ValueError('Video anamorfico: esporta prima una versione con pixel quadrati.')
        # AVColorTransferCharacteristic: SMPTE2084 / ARIB_STD_B67.
        if s.codec_context.color_trc in (16, 18):
            raise ValueError('Sorgente HDR: questa versione Video Edit richiede un master SDR.')
        start = float(s.start_time * s.time_base) if s.start_time is not None else float(first.time or 0)
        origin = float(container.start_time/av.time_base) if container.start_time is not None else start
        return dict(width=s.width, height=s.height, fps=float(rate), fps_ratio=str(rate),
                    duration=duration, frames=int(s.frames or 0), video_start=start,
                    video_offset=start-origin, audio=bool(container.streams.audio),
                    audio_codecs=[x.codec_context.name for x in container.streams.audio],
                    generation_frames=list(EDIT_FRAMES), generation_fps=24,
                    min_seconds=EDIT_FRAMES[0]/24, max_seconds=EDIT_FRAMES[-1]/24)


def plan_interval(meta, start, end):
    start, end = float(start), float(end)
    if not all(math.isfinite(v) for v in (start, end)):
        raise ValueError('Selezione temporale non valida.')
    fps = Fraction(meta['fps_ratio'])
    # Same grid used by the mouse handles. Frames are used for the visible
    # selection; inference has at most one source-frame of extra tail, cropped.
    start_frame = round(start * float(fps))
    end_frame = round(end * float(fps))
    count = end_frame-start_frame
    choices = {int(Fraction(n,24)*fps): n for n in EDIT_FRAMES}
    if count not in choices:
        raise ValueError('La durata non è sulla griglia H3: regola le maniglie nella timeline.')
    start, end = start_frame/float(fps), end_frame/float(fps)
    if start < 0 or end > meta['duration'] + 1e-6:
        raise ValueError('La selezione supera il video sorgente.')
    return dict(start=start, end=end, duration=end-start, generation_frames=choices[count],
                source_frames=count, start_frame=start_frame, end_frame=end_frame)


def check_config(c, input_file):
    e = c['edit']
    if not e.get('source'):
        raise ValueError('Carica il video da modificare.')
    meta = probe(input_file(e['source']))
    plan = plan_interval(meta,e['start'],e['end'])
    if not 0 <= float(e['fade']) <= .5:
        raise ValueError('Raccordo: da 0 a 0,5 secondi.')
    if not 1 <= int(e['steps']) <= 100:
        raise ValueError('Step edit: da 1 a 100.')
    if not 0 <= float(e['lying_start']) <= float(e['lying_end']) <= 1:
        raise ValueError('Intervallo Lying Sigma non valido.')
    if not c['prompt'].strip():
        raise ValueError('Descrivi la modifica da applicare.')
    videos = [r for r in c['refs'] if r.get('kind') == 'video']
    if len(videos)>2 or len(c['refs'])>11:
        raise ValueError('Il sorgente occupa Video 1: restano 2 video e 9 immagini reference (11 file).')
    duration = plan['generation_frames']/24
    for r in c['refs']:
        if r.get('kind') not in ('image','video') or not r.get('name'):
            raise ValueError('Carica o rimuovi le reference vuote.')
        path = input_file(r['name'])
        if r['kind']=='video':
            ref = probe(path)
            if not 2 <= ref['duration'] <= 15:
                raise ValueError('Ogni video reference aggiuntivo deve durare da 2 a 15 secondi.')
            if max(5,math.floor((ref['duration']*24-5)/17)*17+5)>plan['generation_frames']:
                raise ValueError('Un video reference è più lungo del tratto editato: accorcialo prima di caricarlo.')
            duration += ref['duration']
    if duration>15+1e-6:
        raise ValueError(f'Sorgente selezionato + video reference: {duration:.2f} s. Il limite H3 è 15 s totali; accorcia la selezione o le reference.')
    ffmpeg()  # Fail before loading models.
    return meta,plan


def segment_tensor(path, start, n, width, height, interrupt=lambda:None):
    """Seek near the selection; sample by timestamps, with no temporal stretch."""
    import av
    import numpy as np
    import torch
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        origin = float(stream.start_time*stream.time_base) if stream.start_time is not None else 0.
        container.seek(int((origin+start)/float(stream.time_base)),stream=stream,backward=True)
        targets = [origin+start+i/24 for i in range(n)]
        result = torch.empty((n,height,width,3),dtype=torch.float32)
        prev = None; pos = 0
        def put(frame):
            nonlocal pos
            arr = frame.to_ndarray(format='rgb24')
            h,w = arr.shape[:2]
            if w>width or h>height:
                raise ValueError('Dimensioni sorgente cambiate durante la lettura.')
            arr = np.pad(arr,((0,height-h),(0,width-w),(0,0)),mode='edge')
            result[pos] = torch.from_numpy(arr.astype(np.float32)/255.)
            pos+=1
        for frame in container.decode(stream):
            interrupt()
            if frame.time is None:
                raise ValueError('Il sorgente non ha timestamp utilizzabili.')
            t = float(frame.time)
            while pos<n and targets[pos]<t-1e-7:
                put(prev if prev is not None else frame)
            prev=frame
            if pos==n: break
        if prev is None:
            raise ValueError('Impossibile decodificare la selezione.')
        while pos<n: put(prev)
    return result


def thumbnail(path, second):
    import av
    import io
    with av.open(str(path)) as container:
        s=container.streams.video[0]
        origin=float(s.start_time*s.time_base) if s.start_time is not None else 0.
        target=origin+max(0.,float(second))
        container.seek(int(target/float(s.time_base)),stream=s,backward=True)
        chosen=None
        for frame in container.decode(s):
            chosen=frame
            if float(frame.time or 0)>=target: break
        if chosen is None: raise ValueError('Fotogramma non disponibile.')
        image=chosen.to_image(); image.thumbnail((256,144))
        data=io.BytesIO(); image.save(data,format='JPEG',quality=78)
        return data.getvalue()


def save_patch(images,path,width,height,n,interrupt=lambda:None):
    import av
    import numpy as np
    if len(images)<n or images.shape[1]<height or images.shape[2]<width:
        raise ValueError('H3 ha restituito dimensioni o durata inferiori a quelle richieste.')
    with av.open(str(path),'w') as out:
        stream=out.add_stream('ffv1',rate=24)
        stream.width=width; stream.height=height; stream.pix_fmt='bgr0'
        for i,img in enumerate(images[:n]):
            interrupt()
            arr=(img[:height,:width,:3].detach().cpu().numpy().clip(0,1)*255).round().astype(np.uint8)
            frame=av.VideoFrame.from_ndarray(arr,format='rgb24');frame.pts=i;frame.time_base=Fraction(1,24)
            for packet in stream.encode(frame): out.mux(packet)
        for packet in stream.encode(): out.mux(packet)


def compose(source,patch,dest,meta,plan,fade,interrupt=lambda:None):
    """FFmpeg streams the full source; AI touches only the bounded patch.

    Keep original timestamps (including VFR) and audio. Video is re-encoded CRF16;
    it is not a bit-exact stream-copy. No frame interpolation or geometry change.
    """
    start=plan['start']+meta.get('video_offset',0)
    end=plan['end']+meta.get('video_offset',0)
    duration=plan['duration']; fade=min(float(fade),duration/2)
    patch_filter=f'[1:v]trim=duration={duration:.9f},setpts=PTS-STARTPTS,format=rgba'
    if fade:
        patch_filter+=f',fade=t=in:st=0:d={fade:.9f}:alpha=1,fade=t=out:st={duration-fade:.9f}:d={fade:.9f}:alpha=1'
    patch_filter+=f',setpts=PTS+{start:.9f}/TB[p];'
    filters=patch_filter+f"[0:v:0][p]overlay=eof_action=pass:repeatlast=0:enable='gte(t,{start:.9f})*lt(t,{end:.9f})':format=auto[v]"
    # MP4 supports AAC/MP3/ALAC/AC3/EAC3. Other source audio is encoded once.
    copy_audio=all(x in ('aac','mp3','alac','ac3','eac3') for x in meta['audio_codecs'])
    pix='yuv420p' if meta['width']%2==0 and meta['height']%2==0 else 'yuv444p'
    args=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y',
          '-noautorotate','-i',str(source),'-i',str(patch),'-filter_complex',filters,
          '-map','[v]','-map','0:a?','-map_metadata','0','-map_chapters','0',
          '-c:v','libx264','-crf','16','-preset','medium','-pix_fmt',pix,
          '-fps_mode','passthrough','-enc_time_base:v','1:1000000',
          '-c:a','copy' if copy_audio else 'aac']
    if not copy_audio: args+=['-b:a','320k']
    args+=['-movflags','+faststart',str(dest)]
    with tempfile.TemporaryFile() as log:
        process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log)
        try:
            while process.poll() is None:
                interrupt();time.sleep(.1)
            if process.returncode:
                log.seek(0)
                raise ValueError('Ricostruzione video fallita: '+log.read().decode(errors='replace')[-4000:])
        except BaseException:
            if process.poll() is None: process.kill();process.wait()
            dest.unlink(missing_ok=True)
            raise
    return {'audio_copied':copy_audio,'fps':meta['fps'],'width':meta['width'],'height':meta['height']}


def run_edit(c,root,st,update,progress,uid):
    from . import dogma_h3_director_v134 as director
    import comfy.model_management as mm
    from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo,MiniMaxH3AddGuide
    import uuid
    import re
    meta,plan=check_config(c,director.input_file)
    source=director.input_file(c['edit']['source'])
    width=math.ceil(meta['width']/32)*32; height=math.ceil(meta['height']/32)*32
    n=plan['generation_frames']
    update('running','Lettura della sola selezione…',active='edit')
    selected=segment_tensor(source,plan['start'],n,width,height,mm.throw_exception_if_processing_interrupted)
    images={};videos={'ref_video_1':selected}
    for r in c['refs']:
        if r['kind']=='image':images[f'ref_image_{len(images)+1}']=director.load_image(r['name'])
        else:
            p=director.input_file(r['name']);m=probe(p)
            rn=max(5,math.floor((m['duration']*24-5)/17)*17+5)
            # Native H3 truncates refs to output length. Fail rather than silently
            # ignore requested reference content.
            if rn>n: raise ValueError('Un video reference è più lungo del tratto editato: accorcialo prima di caricarlo.')
            videos[f'ref_video_{len(videos)+1}']=segment_tensor(p,0,rn,math.ceil(m['width']/32)*32,math.ceil(m['height']/32)*32,mm.throw_exception_if_processing_interrupted)
    update('running',f'Video Edit · {meta["width"]} × {meta["height"]} · caricamento Ref2VA')
    res=director.load_resources(c)
    prompt=('integrated_multimodal_description:\n[Shot 1]\n'
            'The target video is an edited version of <Video 1>. Preserve its shot, camera, '
            'timing, motion and all elements not explicitly requested to change. '
            'Keep the beginning and ending visually continuous with the source. '
            'Apply only the following edit, using additional references as specified:\n'+c['prompt'].strip())
    cond,latent=MiniMaxH3ReferenceToVideo.execute(res['clip'],prompt,width,height,n,'match',
        vae=res['vae'],audio_vae=res['audio'],ref_images=images,ref_videos=videos)
    if c['edit']['anchor_edges']:
        cond=MiniMaxH3AddGuide.execute(cond,latent,0,vae=res['vae'],image=selected[:1])[0]
        cond=MiniMaxH3AddGuide.execute(cond,latent,-1,vae=res['vae'],image=selected[-1:])[0]
    model=director.prepare_model(res,c,{'loras':c['common_loras']},'edit',uid)
    update('running','Video Edit · generazione del tratto selezionato')
    result=director.sample(model,cond,latent,c['edit'],int(c['seed']),progress=progress)
    output,_=director.decode(res,result,False)
    folder=root/'edits'/uuid.uuid4().hex;folder.mkdir(parents=True)
    patch=folder/'segment.mkv'
    update('running','Video Edit · rimozione bordi tecnici e raccordo')
    save_patch(output,patch,meta['width'],meta['height'],n,mm.throw_exception_if_processing_interrupted)
    del result,output,selected,images,videos,cond,latent,model,res
    job=re.sub(r'[^\w.-]+','_',c['job'])[:80] or 'DOGMA'
    final=folder/(job+'_H3_VIDEO_EDIT.mp4')
    update('running','Ricostruzione del video completo · audio originale')
    try:
        info=compose(source,patch,final,meta,plan,c['edit']['fade'],mm.throw_exception_if_processing_interrupted)
    finally:
        patch.unlink(missing_ok=True)
    item=dict(id=uuid.uuid4().hex,label='Video completo · edit applicato',video=director.view_file(final),
              saved_path=director.export_file(final,c),complete=True,kind='edit',selection=plan,
              duration=meta['duration'],config=c,**info)
    st.setdefault('edits',[]).append(item)
    update('done','Video completo pronto. Il tratto editato è già al suo posto.',active=None)


def register_edit_routes(routes,input_file):
    from aiohttp import web
    import asyncio
    from functools import lru_cache
    slots=asyncio.Semaphore(3)

    @lru_cache(maxsize=128)
    def metadata_cached(path,size,mtime):
        return probe(Path(path))

    @lru_cache(maxsize=256)
    def thumbnail_cached(path,size,mtime,second):
        return thumbnail(Path(path),second)

    @routes.get('/dogma/h3/v2/edit/metadata')
    async def metadata_route(request):
        try:
            path=input_file(request.query.get('name',''));s=path.stat()
            async with slots:
                data=await asyncio.to_thread(metadata_cached,str(path),s.st_size,s.st_mtime_ns)
            return web.json_response(data)
        except (ValueError,OSError) as exc:
            raise web.HTTPBadRequest(text=str(exc))

    @routes.get('/dogma/h3/v2/edit/thumbnail')
    async def thumbnail_route(request):
        try:
            path=input_file(request.query.get('name',''));s=path.stat()
            second=float(request.query.get('time','0'))
            if not math.isfinite(second) or not 0<=second<=86400*7:
                raise ValueError('Tempo anteprima non valido.')
            async with slots:
                data=await asyncio.to_thread(thumbnail_cached,str(path),s.st_size,s.st_mtime_ns,round(second,4))
            return web.Response(body=data,content_type='image/jpeg',headers={'Cache-Control':'private, max-age=60'})
        except (ValueError,OSError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
