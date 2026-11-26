"""Selective motion repair. Original timestamps, frame count, audio and size survive.

Detection uses low-resolution tracked motion, never a hard-coded Seedance cadence.
RIFE 4.26 reconstructs only selected times, on the machine running ComfyUI.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from fractions import Fraction

import numpy as np

MODEL_URL = 'https://huggingface.co/hzwer/RIFE/resolve/01fdc7e97404120c243c3ea7b427046e5dc7643e/RIFEv4.26_0921.zip'
ARCHIVE_SHA256 = '1fa9b9cda3d9b8c3e301359e2595960902f97bf926c08598b0e9957a3f3f760e'
WEIGHT_SHA256 = '45c7f74156704769dc9f85cfcaf8552e1e926f9399dcfa3a553dee88fac6f53f'
_MODEL_LOCK = threading.Lock()
_RENDER_LOCK = threading.Lock()


class RepairCancelled(Exception):
    pass


def _check(cancel):
    if cancel:
        cancel()


def _digest(path):
    result=hashlib.sha256()
    with open(path, 'rb') as f:
        while block:=f.read(1024*1024):result.update(block)
    return result.hexdigest()


def model_file(directory, cancel=None, progress=None):
    """Only verified weights are downloaded; remote Python is never executed."""
    directory = Path(directory)
    path = directory / 'rife426.pkl'
    while not _MODEL_LOCK.acquire(timeout=.1):_check(cancel)
    try:
        _check(cancel)
        if path.is_file() and _digest(path) == WEIGHT_SHA256:
            return path
        directory.mkdir(parents=True, exist_ok=True)
        if progress:
            progress('Download modello · solo al primo utilizzo', 0)
        with tempfile.TemporaryDirectory(prefix='rife-', dir=directory) as temp:
            archive = Path(temp) / 'model.zip'
            with urllib.request.urlopen(MODEL_URL, timeout=30) as response, archive.open('wb') as out:
                size = 0
                while block := response.read(1024 * 1024):
                    _check(cancel)
                    size += len(block)
                    if size > 30_000_000:
                        raise ValueError('Download RIFE di dimensione inattesa.')
                    out.write(block)
            if _digest(archive) != ARCHIVE_SHA256:
                raise ValueError('Verifica del modello RIFE non riuscita. Riprova il download.')
            weight = Path(temp) / 'weights.pkl'
            with zipfile.ZipFile(archive) as z:
                weight.write_bytes(z.read('RIFEv4.26_0921/flownet.pkl'))
            if _digest(weight) != WEIGHT_SHA256:
                raise ValueError('Pesi RIFE non validi.')
            _check(cancel)
            weight.replace(path)
        return path
    finally:
        _MODEL_LOCK.release()


def measure_pair(a, b):
    """Track real displacements; pixel differences alone confuse light and motion."""
    import cv2
    af, bf = a.astype(np.float32), b.astype(np.float32)
    diff = float(np.mean(np.abs(bf-af)))
    light = float(abs(np.mean(bf)-np.mean(af)))
    row = dict(diff=diff, brightness=light, motion=0., x=0., y=0., reliability=0., cut=False)
    points = cv2.goodFeaturesToTrack(a, 500, .015, 5)
    if points is None or len(points) < 12:
        row['cut'] = diff > 18
        return row
    q, ok, _ = cv2.calcOpticalFlowPyrLK(a, b, points, None, winSize=(21,21), maxLevel=3)
    back, ok2, _ = cv2.calcOpticalFlowPyrLK(b, a, q, None, winSize=(21,21), maxLevel=3)
    good = (ok[:,0] > 0) & (ok2[:,0] > 0) & (np.linalg.norm(back[:,0]-points[:,0], axis=1) < .6)
    row['reliability'] = float(good.mean())
    vectors = (q[:,0]-points[:,0])[good]
    if len(vectors) >= 12:
        # A camera estimate needs agreement across the image, not just one subject.
        p, tracked = points[good,0], q[good,0]
        transform, inside = cv2.estimateAffinePartial2D(p, tracked, method=cv2.RANSAC,
            ransacReprojThreshold=.25, maxIters=500, confidence=.995, refineIters=5)
        if transform is not None and inside is not None:
            selected=p[inside[:,0]>0];h,w=a.shape
            occupied={(min(3,int(x*4/w)),min(2,int(y*3/h))) for x,y in selected}
            center=np.array([w/2,h/2]);delta=transform[:,:2]@center+transform[:,2]-center
            coverage=float(np.prod(np.ptp(selected,axis=0)/[w,h])) if len(selected)>1 else 0.
            row['camera']=dict(x=float(delta[0]),y=float(delta[1]),
                inliers=float(inside.mean()),coverage=coverage,cells=len(occupied),
                scale=float(np.sqrt(abs(np.linalg.det(transform[:,:2])))),
                angle=float(np.degrees(np.arctan2(transform[1,0],transform[0,0]))))
        magnitudes=np.linalg.norm(vectors,axis=1)
        moving=vectors[magnitudes>max(.05,float(np.percentile(magnitudes,90))*.35)]
        # A moving subject can occupy less than half of an otherwise static shot.
        if np.median(magnitudes)<.04 and len(moving)>=max(12,len(vectors)*.1):vectors=moving
        row['motion'] = float(np.percentile(np.linalg.norm(vectors, axis=1), 75))
        row['x'], row['y'] = map(float, np.median(vectors, axis=0))
    # Histogram changes plus failed tracking distinguish cuts from fast pans.
    ha = cv2.calcHist([a],[0],None,[32],[0,256]); hb = cv2.calcHist([b],[0],None,[32],[0,256])
    ha /= max(1., float(ha.sum())); hb /= max(1., float(hb.sum()))
    hist = cv2.compareHist(ha, hb, cv2.HISTCMP_BHATTACHARYYA)
    row['cut'] = bool((diff > 24 and row['reliability'] < .45) or (diff > 36 and hist > .4))
    return row


def analyze(source, cancel=None, progress=None):
    import av
    import cv2
    start = time.perf_counter()
    with av.open(str(source)) as c:
        v = c.streams.video[0]
        v.thread_type = 'AUTO';v.thread_count=4
        fps = v.average_rate or v.base_rate
        if not fps or fps <= 0:
            raise ValueError('Il video non dichiara un framerate valido.')
        meta = dict(fps=str(fps), time_base=str(v.time_base), width=v.width, height=v.height,
                    pixel_format=v.format.name, bit_depth=max(x.bits for x in v.format.components),
                    color_range=v.codec_context.color_range, colorspace=v.codec_context.colorspace,
                    color_primaries=v.codec_context.color_primaries, color_trc=v.codec_context.color_trc,
                    audio_streams=len(c.streams.audio), sample_aspect_ratio=str(v.sample_aspect_ratio or Fraction(1)),
                    duration=float(v.duration*v.time_base) if v.duration else None)
        frames, pts, durations, metrics = [], [], [], []
        width = min(384, v.width); height = max(16, round(v.height * width / v.width))
        for i, f in enumerate(c.decode(v)):
            _check(cancel)
            # swscale shrinks before transferring the ndarray.
            gray = f.reformat(width=width, height=height, format='gray').to_ndarray()
            metrics.append(measure_pair(frames[-1], gray) if frames else dict(diff=0.,brightness=0.,motion=0.,x=0.,y=0.,reliability=1.,cut=False))
            frames.append(gray)
            pts.append(int(f.pts) if f.pts is not None else round(i/fps/v.time_base))
            durations.append(int(f.duration or round(1/fps/v.time_base)))
            if progress and i % 12 == 0:
                progress('Analisi movimento', .18 * min(1., (i+1)/max(1,v.frames or i+12)))
        if not frames:
            raise ValueError('Il video non contiene fotogrammi decodificabili.')
        if any(b <= a for a,b in zip(pts,pts[1:])):
            raise ValueError('I timestamp del video non sono crescenti.')
        meta.update(frames=len(frames), pts=pts, durations=durations,
                    analysis_seconds=round(time.perf_counter()-start,3))
        return meta, frames, metrics


def plan_repair(metrics, times, fps):
    """Infer held frames and isolated/periodic jumps, with fixed local endpoints."""
    n = len(metrics)
    positions = np.arange(n, dtype=float)
    motion = np.array([x['motion'] for x in metrics])
    cuts = {i for i,m in enumerate(metrics) if m['cut']}
    ratios = np.ones(n)
    eligible = np.zeros(n, dtype=bool)
    for i in range(3,n-3):
        if any(x in cuts for x in range(i-3,i+4)):
            continue
        nearby = np.r_[motion[i-3:i], motion[i+1:i+4]]
        base = float(np.median(nearby))
        if base < .045:
            continue
        ratios[i] = motion[i]/base
        before = np.array([np.median([metrics[j][k] for j in range(i-3,i)]) for k in ('x','y')])
        after = np.array([np.median([metrics[j][k] for j in range(i+1,i+4)]) for k in ('x','y')])
        current = np.array([metrics[i]['x'],metrics[i]['y']])
        cosine = lambda x,y: float(np.dot(x,y)/max(1e-8,np.linalg.norm(x)*np.linalg.norm(y)))
        eligible[i] = (metrics[i]['reliability'] > .65 and cosine(before,after) > .9
                       and cosine(current,before+after) > .75
                       and .6 < np.median(motion[i-3:i])/max(.01,np.median(motion[i+1:i+4])) < 1.67
                       and metrics[i]['brightness'] < max(.8,metrics[i]['diff']*.65))
    spikes = {i for i in range(n) if eligible[i] and 1.65 < ratios[i] < 3.1}
    patterns = []
    # Search the cadence; do not assume 24 frames, 24 fps, or phase zero.
    eligible_indices=np.flatnonzero(eligible);spike_indices=np.array(sorted(spikes),dtype=int)
    for period in range(2, min(121, n//3+1)):
        counts=np.bincount(eligible_indices%period,minlength=period)
        hits=np.bincount(spike_indices%period,minlength=period)
        for phase in np.flatnonzero((hits>=3)&(hits/np.maximum(1,counts)>=.65)):
            patterns.append(dict(period=period,phase=int(phase),support=int(hits[phase]),count=int(counts[phase])))
    patterns.sort(key=lambda x:(x['support']/x['count'],x['support'],-x['period']),reverse=True)
    pattern = patterns[0] if patterns else None
    if pattern:
        spikes.update(i for i in range(3,n-3) if eligible[i] and i%pattern['period']==pattern['phase'] and ratios[i]>1.22)
        pattern['seconds'] = round(pattern['period']/float(fps),6)
    duplicates = []
    i = 2
    while i < n-2:
        rest = float(np.median(motion[max(1,i-3):i]))
        if rest < .06 or metrics[i]['diff'] > .65 or motion[i] > rest*.16:
            i += 1; continue
        first = i
        while i < n-1 and metrics[i]['diff'] < .65 and motion[i] < rest*.16:
            i += 1
        last = i-1
        # Long pauses and the beginning/end of a shot remain intentional holds.
        if (last-first < max(1,min(4,round(float(fps)*.15))) and i<n-1
            and not any(j in cuts for j in range(first-1,i+2))
            and motion[i] > rest*1.45 and metrics[i]['reliability']>.65):
            duplicates.append((first,last))
            spikes.discard(i)
    groups = []
    for i in sorted(spikes):
        left, right = i-3, i+2
        if groups and left <= groups[-1][1]:
            groups[-1] = (groups[-1][0],max(right,groups[-1][1]))
        else:
            groups.append((left,right))
    for left,right in groups:
        durations = np.diff(times[left:right+1])
        units = durations.copy()
        for j in range(left+1,right+1):
            if j in spikes:
                units[j-left-1] *= min(2.5, max(1.22,ratios[j]))
        physical = np.r_[0., np.cumsum(units)]
        target = (times[left:right+1]-times[left])/(times[right]-times[left])*physical[-1]
        positions[left:right+1] = np.interp(target,physical,np.arange(left,right+1))
    for first,last in duplicates:
        left,right = first-1,last+1
        positions[first:last+1] = left+(times[first:last+1]-times[left])/(times[right]-times[left])*(right-left)
    requests = {}
    for i, pos in enumerate(positions):
        run = next(((a,b) for a,b in duplicates if a<=i<=b),None)
        if abs(pos-i) < .025 and run is None:
            continue
        left = int(math.floor(pos)); right = left+1; alpha = float(pos-left)
        # Held runs must interpolate between the two distinct endpoint images.
        if run:
            left,right = run[0]-1,run[1]+1
            alpha = float((times[i]-times[left])/(times[right]-times[left]))
        if alpha < .025 or alpha > .975 or right in cuts:
            continue
        requests[i] = (left,right,alpha)
    return requests, dict(jump_frames=sorted(spikes),held_ranges=[list(x) for x in duplicates],
                          cadence=pattern, cuts=sorted(cuts), repaired_frames=sorted(requests),
                          regions=[list(x) for x in groups],
                          jump_ratios={str(i):round(float(ratios[i]),3) for i in sorted(spikes)})


def plan_camera(metrics, times, fps, details, shape):
    """Small translation refinement only in reliably tracked, stuttering pans.

    This is not general stabilization: clean shots, cuts, handheld movement,
    zoom/rotation and large corrections are deliberately left alone.
    """
    from scipy.signal import savgol_filter
    n=len(metrics);actual=np.zeros((n,2));target=np.zeros((n,2));enabled=np.zeros(n,dtype=bool)
    h,w=shape;limit=np.array([w,h])*.004
    shots=list(zip([0,*details['cuts']],[*details['cuts'],n]))
    accepted=[]
    for first,end in shots:
        count=end-first
        events=[i for i in details['jump_frames'] if first<i<end]
        if count<max(12,float(fps)*.6) or len(events)<2:continue
        cameras=[m.get('camera') for m in metrics[first+1:end]]
        if any(c is None for c in cameras):continue
        reliable=[c['inliers']>=.55 and c['coverage']>=.3 and c['cells']>=6
                  and abs(c['scale']-1)<.003 and abs(c['angle'])<.15 for c in cameras]
        if np.mean(reliable)<.95:continue
        velocity=np.array([[c['x'],c['y']] for c in cameras])
        axis=int(np.argmax(np.abs(np.median(velocity,axis=0))))
        speed=velocity[:,axis];direction=np.sign(np.median(speed))
        if np.median(np.abs(speed))<.08 or np.mean(speed*direction>=-.025)<.95:continue
        path=np.vstack([np.zeros(2),np.cumsum(velocity,axis=0)])
        grid=np.linspace(times[first],times[end-1],count)
        uniform=np.stack([np.interp(grid,times[first:end],path[:,a]) for a in range(2)],axis=1)
        window=min(count if count%2 else count-1,max(7,round(float(fps))//2*2+1))
        smooth=savgol_filter(uniform,window,3,axis=0)
        smooth=np.stack([np.interp(times[first:end],grid,smooth[:,a]) for a in range(2)],axis=1)
        smooth-=smooth[0]
        smooth+=((times[first:end]-times[first])/(times[end-1]-times[first]))[:,None]*(path[-1]-smooth[-1])
        offset=smooth-path
        # Reject the whole shot instead of clipping shifts and creating new jerks.
        if np.any(np.max(np.abs(offset),axis=0)>limit):continue
        actual[first:end]=path;target[first:end]=smooth;enabled[first:end]=True
        accepted.append([first,end-1])
    return actual,target,enabled,dict(shots=accepted,limit_fraction=.004)


def _matrix(meta):
    # swscale's matrix IDs differ from AVColorSpace for SMPTE170M.
    return {1:1,4:4,5:5,6:5,7:7,9:9,10:9}.get(meta['colorspace'],5)


class Interpolator:
    def __init__(self, weights, device=None, meta=None):
        import torch
        from .dogma_rife_arch import IFNet
        self.device = torch.device(device or ('cuda' if torch.cuda.is_available() else 'cpu'))
        self.meta=meta
        if self.device.type=='cuda':
            try:
                import comfy.model_management as management
                # Release other Comfy models only when this render actually needs VRAM.
                pixels=(meta['width']*meta['height']) if meta else 2073600
                management.free_memory(max(2_500_000_000,pixels*1200),self.device)
            except ImportError:pass
        self.model = IFNet()
        state = torch.load(weights,map_location='cpu',weights_only=True)
        state = {k.removeprefix('module.'):v for k,v in state.items()}
        state = {k:v for k,v in state.items() if not k.startswith(('teacher.','caltime.'))}
        self.model.load_state_dict(state,strict=True)
        self.model.eval().to(self.device)
        self.cache = {}

    def frame(self, first, second, alpha):
        import torch
        import torch.nn.functional as F
        import av
        h,w = first.height,first.width
        def tensor(frame):
            key = frame.pts
            if key not in self.cache:
                if self.meta:
                    rgb=frame.reformat(format='rgb48le',src_colorspace=_matrix(self.meta),src_color_range=self.meta['color_range'] or 1,dst_color_range=2)
                    a=rgb.to_ndarray().astype(np.float32)/65535.
                else:a = frame.to_ndarray(format='rgb48le').astype(np.float32)/65535.
                self.cache[key] = torch.from_numpy(a).permute(2,0,1).unsqueeze(0).to(self.device)
            return self.cache[key]
        a,b = tensor(first),tensor(second)
        self.cache = {k:v for k,v in self.cache.items() if k in (first.pts,second.pts)}
        x = F.pad(torch.cat((a,b),1),(0,(-w)%64,0,(-h)%64),mode='replicate')
        with torch.inference_mode():
            result = self.model(x,alpha,[16,8,4,2,1])[2][-1][0,:,:h,:w]
            rgb=result.permute(1,2,0).cpu().numpy()
        # CPU conversion avoids several seconds of first-use CUDA kernel compilation.
        if not np.isfinite(rgb).all():
            raise ValueError('RIFE ha prodotto un fotogramma non valido.')
        rgb=np.rint(np.clip(rgb,0,1)*65535).astype(np.uint16)
        return av.VideoFrame.from_ndarray(rgb,format='rgb48le')

    def close(self):
        from .dogma_rife_arch import backwarp_tenGrid
        self.cache.clear();backwarp_tenGrid.clear()
        self.model.to('cpu')


def _encoder(path, meta):
    import av
    depth = meta['bit_depth'] > 8
    candidates = [('hevc_nvenc','p010le' if depth else 'yuv420p',dict(preset='p5',tune='hq',rc='vbr',cq='16',b='0',profile='main10' if depth else 'main')),
                  ('libx265','yuv420p10le' if depth else 'yuv420p',dict(preset='fast',crf='14',**{'x265-params':'log-level=error:pools=4'}))]
    errors = []
    for codec,pixel,options in candidates:
        container = None
        try:
            # MP4's default 1000 Hz movie clock truncates fractional-frame ends
            # in edit lists (e.g. 457/24 s became 19.041015625 s). Use the source
            # clock for both the movie and video track; keep strict verification.
            clock=str(Fraction(meta['time_base']).denominator)
            container = av.open(str(path),'w',format='mp4',options={
                'movflags':'+faststart','movie_timescale':clock,'video_track_timescale':clock})
            stream = container.add_stream(codec,rate=Fraction(meta['fps']))
            stream.width=meta['width'];stream.height=meta['height'];stream.pix_fmt=pixel;stream.options=options
            stream.time_base=Fraction(meta['time_base']);stream.codec_context.time_base=stream.time_base
            stream.codec_context.codec_tag='hvc1'
            stream.codec_context.sample_aspect_ratio=Fraction(meta['sample_aspect_ratio'])
            for name in ('color_range','colorspace','color_primaries','color_trc'):
                setattr(stream.codec_context,name,meta[name])
            stream.codec_context.open()
            return container,stream,codec
        except Exception as exc:
            errors.append(str(exc))
            if container:
                container.close()
    raise RuntimeError('Codifica video non disponibile: '+'; '.join(errors))


def _translate_frame(frame, shift, meta):
    """Shift native YUV planes: avoid two full RGB conversions per camera frame."""
    import av
    import cv2
    deep=meta['bit_depth']>8;pixel='yuv420p10le' if deep else 'yuv420p'
    if frame.format.name=='rgb48le':
        frame=frame.reformat(format=pixel,src_colorspace=_matrix(meta),dst_colorspace=_matrix(meta),src_color_range=2,dst_color_range=meta['color_range'] or 1)
    else:frame=frame.reformat(format=pixel)
    result=av.VideoFrame(frame.width,frame.height,pixel)
    dtype=np.uint16 if deep else np.uint8;itemsize=2 if deep else 1
    for source,destination in zip(frame.planes,result.planes):
        a=np.ndarray((source.height,source.line_size//itemsize),dtype=dtype,buffer=source)[:,:source.width]
        matrix=np.array([[1,0,shift[0]*source.width/frame.width],[0,1,shift[1]*source.height/frame.height]],dtype=np.float32)
        moved=cv2.warpAffine(a,matrix,(source.width,source.height),flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_REFLECT_101)
        if deep:np.minimum(moved,1023,out=moved)
        target=np.ndarray((destination.height,destination.line_size//itemsize),dtype=dtype,buffer=destination)
        target[:,:destination.width]=moved
    for name in ('color_range','colorspace','color_primaries','color_trc'):setattr(result,name,meta[name])
    return result


def _verify(source, output, meta):
    import av
    with av.open(str(output)) as c:
        v=c.streams.video[0]
        frames=list((f.pts*f.time_base) for f in c.decode(v))
        expected=[p*Fraction(meta['time_base']) for p in meta['pts']]
        tolerance=max(Fraction(meta['time_base']),v.time_base)
        if len(frames)!=len(expected) or any(abs(a-b)>tolerance for a,b in zip(frames,expected)):
            raise ValueError('La verifica dei fotogrammi o della sincronizzazione non è riuscita.')
        if (v.width,v.height)!=(meta['width'],meta['height']):
            raise ValueError('La risoluzione del file corretto è cambiata.')
        if max(x.bits for x in v.format.components)<meta['bit_depth']:
            raise ValueError('La profondità colore del file corretto è cambiata.')
        for name in ('color_range','colorspace','color_primaries','color_trc'):
            if meta[name]!=(0 if name=='color_range' else 2) and getattr(v.codec_context,name)!=meta[name]:
                raise ValueError('I metadati colore del file corretto sono cambiati.')
        if len(set(np.diff(meta['pts'])))==1 and v.average_rate!=Fraction(meta['fps']):
            raise ValueError('Il framerate del file corretto è cambiato.')
        if meta['duration'] is not None and v.duration and abs(float(v.duration*v.time_base)-meta['duration'])>float(tolerance)*2:
            raise ValueError('La durata del file corretto è cambiata.')
        if len(c.streams.audio)!=meta['audio_streams']:
            raise ValueError('Una traccia audio è assente dal file corretto.')
    def audio_signature(path):
        signatures=[]
        with av.open(str(path)) as c:
            states={s.index:[hashlib.sha256(),[]] for s in c.streams.audio}
            for pk in c.demux(list(c.streams.audio)) if c.streams.audio else []:
                if not pk.size:continue
                h,ts=states[pk.stream.index];h.update(bytes(pk));ts.append((str(pk.pts*pk.time_base) if pk.pts is not None else None,str(pk.duration*pk.time_base)))
            signatures=[(h.hexdigest(),ts) for h,ts in states.values()]
        return signatures
    if audio_signature(source)!=audio_signature(output):
        raise ValueError('La verifica audio non è riuscita: originale conservato.')


def repair_video(source, output, model_directory, cancel=None, progress=None, device=None):
    """Write a second file atomically. Failure never damages the original."""
    import av
    source,output=Path(source).resolve(),Path(output).resolve()
    if source==output or output.exists():
        raise ValueError('Il fix richiede un nuovo file, distinto dall’originale.')
    start=time.perf_counter()
    meta,thumbs,metrics=analyze(source,cancel,progress)
    times=np.array(meta['pts'],dtype=float)*float(Fraction(meta['time_base']))
    requests,details=plan_repair(metrics,times,Fraction(meta['fps']))
    camera_actual,camera_target,camera_enabled,camera_details=plan_camera(metrics,times,Fraction(meta['fps']),details,thumbs[0].shape)
    report=dict(version=2,engine='RIFE 4.26 + restrained camera refinement',**{k:meta[k] for k in ('frames','fps','width','height','bit_depth','duration','audio_streams','analysis_seconds')},**details,
                camera_refinement=camera_details)
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.dogma-fix-',suffix='.mp4',dir=output.parent);os.close(fd);temp=Path(temp)
    interpolator=None;out=None
    try:
        if not requests:
            shutil.copyfile(source,temp)
            report.update(status='unchanged',interpolated_frames=0,encoder='stream copy')
        else:
            weights=model_file(model_directory,cancel,progress)
            if progress:progress('Attesa correzione video',.2)
            # Bound GPU/RAM use when several API branches finish together.
            while not _RENDER_LOCK.acquire(timeout=.1):_check(cancel)
            try:
                _check(cancel)
                interpolator=Interpolator(weights,device,meta)
                out,video_out,codec=_encoder(temp,meta)
                report['encoder']=codec;report['device']=str(interpolator.device)
                render_start=time.perf_counter();cache={};current=-1;corrected_thumbs=list(thumbs);shifted=[];largest_shift=np.zeros(2)
                with av.open(str(source)) as incoming:
                    original_video=incoming.streams.video[0];original_video.thread_type='AUTO';original_video.thread_count=4
                    audio={s.index:out.add_stream_from_template(s) for s in incoming.streams.audio}
                    def decoded():
                        for packet in incoming.demux([original_video,*incoming.streams.audio]):
                            _check(cancel)
                            if packet.stream.index==original_video.index:
                                yield from packet.decode()
                            elif packet.size and packet.dts is not None:
                                packet.stream=audio[packet.stream.index];out.mux(packet)
                    frames=iter(decoded())
                    for i in range(meta['frames']):
                        _check(cancel)
                        left,right,alpha=requests.get(i,(i,i,0.))
                        while current<max(i,right):
                            current+=1;cache[current]=next(frames)
                        if i in requests:
                            frame=interpolator.frame(cache[left],cache[right],alpha)
                        else:frame=cache[i]
                        if camera_enabled[i]:
                            pose=camera_actual[i]
                            if i in requests:
                                small=frame.reformat(width=thumbs[i].shape[1],height=thumbs[i].shape[0],format='gray').to_ndarray()
                                measured=measure_pair(thumbs[left],small).get('camera')
                                if measured and measured['inliers']>=.55:
                                    pose=camera_actual[left]+[measured['x'],measured['y']]
                                else:pose=camera_actual[left]*(1-alpha)+camera_actual[right]*alpha
                            shift=(camera_target[i]-pose)*[meta['width']/thumbs[i].shape[1],meta['height']/thumbs[i].shape[0]]
                            if np.max(np.abs(shift))>.04:
                                # At most a narrow edge strip is extended; no crop or zoom.
                                frame=_translate_frame(frame,shift,meta);shifted.append(i)
                                largest_shift=np.maximum(largest_shift,np.abs(shift))
                        if frame.format.name=='rgb48le':
                            frame=frame.reformat(format=video_out.pix_fmt,src_colorspace=_matrix(meta),dst_colorspace=_matrix(meta),src_color_range=2,dst_color_range=meta['color_range'] or 1)
                            for name in ('color_range','colorspace','color_primaries','color_trc'):setattr(frame,name,meta[name])
                        if i in requests or camera_enabled[i]:
                            corrected_thumbs[i]=frame.reformat(width=thumbs[i].shape[1],height=thumbs[i].shape[0],format='gray').to_ndarray()
                        frame=frame.reformat(format=video_out.pix_fmt)
                        frame.pts=meta['pts'][i];frame.time_base=Fraction(meta['time_base'])
                        for packet in video_out.encode(frame):out.mux(packet)
                        # Keep endpoints of a held run until its last replacement.
                        upcoming=[requests[j][0] for j in range(i+1,min(i+7,meta['frames'])) if j in requests]
                        keep=min([i+1,*upcoming])
                        cache={k:v for k,v in cache.items() if k>=keep}
                        if progress and i%4==0:progress('Correzione scatti',.2+.65*(i+1)/meta['frames'])
                    # Drain trailing audio packets after the final video frame.
                    for _ in frames:pass
                    for packet in video_out.encode():out.mux(packet)
                out.close();out=None
                report['render_seconds']=round(time.perf_counter()-render_start,3)
                report['interpolated_frames']=len(requests)
                report['camera_refinement'].update(adjusted_frames=len(shifted),max_shift_pixels=largest_shift.tolist(),edge_fill='reflect, narrow edge strip only')
                report['status']='repaired'
                # A motion-only acceptance gate prevents a worse cadence from being labelled fixed.
                after=list(metrics)
                affected=sorted({j for i in {*requests,*shifted} for j in (i,i+1) if 0<j<len(thumbs)})
                for i in affected:after[i]=measure_pair(corrected_thumbs[i-1],corrected_thumbs[i])
                def jitter(rows):
                    value=[]
                    for left,right in details['regions']+[(a-1,b+1) for a,b in details['held_ranges']]:
                        v=np.array([rows[j]['motion'] for j in range(left+1,right+1)])
                        if v.size>2:value.append(float(np.std(v)/max(.01,np.mean(v))))
                    return float(np.mean(value)) if value else None
                report['motion_jitter_before']=jitter(metrics);report['motion_jitter_after']=jitter(after)
                def camera_jerk(rows):
                    values=[]
                    for first,last in camera_details['shots']:
                        velocity=np.array([[r.get('camera',{}).get('x',r['x']),r.get('camera',{}).get('y',r['y'])] for r in rows[first+1:last+1]])
                        acceleration=np.linalg.norm(np.diff(velocity,axis=0),axis=1)
                        if acceleration.size:values.extend(acceleration.tolist())
                    return dict(rms=float(np.sqrt(np.mean(np.square(values)))),peak=float(max(values))) if values else None
                report['camera_jerk_before']=camera_jerk(metrics);report['camera_jerk_after']=camera_jerk(after)
                camera_worse=np.any(largest_shift>np.array([meta['width'],meta['height']])*.004) or (report['camera_jerk_before'] and (report['camera_jerk_after']['rms']>report['camera_jerk_before']['rms']*.9
                               or report['camera_jerk_after']['peak']>report['camera_jerk_before']['peak']))
                if camera_worse or (report['motion_jitter_before'] is not None and report['motion_jitter_after']>report['motion_jitter_before']*.95):
                    shutil.copyfile(source,temp)
                    report.update(status='skipped_quality',interpolated_frames=0)
                    report['camera_refinement']['adjusted_frames']=0
            finally:
                if interpolator:interpolator.close()
                _RENDER_LOCK.release()
        _check(cancel)
        if progress:progress('Verifica sincronizzazione',.9)
        _verify(source,temp,meta)
        _check(cancel)
        temp.replace(output)
        report['total_seconds']=round(time.perf_counter()-start,3)
        if progress:progress('Correzione completata',1.)
        return report
    finally:
        if out:out.close()
        if temp.exists():temp.unlink()
