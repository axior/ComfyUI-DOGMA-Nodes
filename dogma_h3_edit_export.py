"""Frame-exact restitch and lossless export in the source colour planes."""
from pathlib import Path
from fractions import Fraction
import subprocess,tempfile,time,itertools
import av
import numpy as np
from .dogma_h3_edit_mask import FrameReader,composite_mask,composite_settings,resize_rgb,resize_alpha,fade_weight

YUV_FORMATS={'yuv420p','yuv422p','yuv444p','yuvj420p','yuvj422p','yuvj444p','yuv420p10le','yuv422p10le','yuv444p10le','gray','gray10le'}

def output_format(frame):
    name=frame.format.name
    name={'nv12':'yuv420p','nv21':'yuv420p','nv16':'yuv422p','nv20le':'yuv422p10le','gray8':'gray'}.get(name,name)
    if name in YUV_FORMATS:return name,'libx264'
    if name in ('rgb24','bgr24','rgba','bgra','bgr0','rgb0','0rgb','0bgr'):return 'rgb24','libx264rgb'
    raise ValueError('Export senza perdita non disponibile per '+frame.format.name+'. Usa un sorgente SDR YUV a 8/10 bit o RGB a 8 bit.')

def plane_array(plane,fmt):
    dtype=np.dtype('<u2') if '10le' in fmt else np.dtype('u1')
    channels=3 if fmt=='rgb24' else 1
    return np.ndarray((plane.height,plane.line_size//dtype.itemsize),dtype=dtype,buffer=plane)[:,:plane.width*channels]

def plane_mask(alpha,width,height):
    if alpha.shape==(height,width):return alpha
    sy=(alpha.shape[0]+height-1)//height;sx=(alpha.shape[1]+width-1)//width
    padded=np.pad(alpha,((0,height*sy-alpha.shape[0]),(0,width*sx-alpha.shape[1])),mode='edge')
    result=padded.reshape(height,sy,width,sx).min(axis=(1,3))
    # Decoder chroma interpolation also reads adjacent samples. Keep that small
    # shared neighbourhood original so protected RGB pixels remain untouched.
    from scipy.ndimage import minimum_filter
    return minimum_filter(result,size=(3 if sy>1 else 1,3 if sx>1 else 1),mode='nearest')

def blend_frame(original,replacement,alpha,fmt):
    base=original if original.format.name==fmt else original.reformat(format=fmt)
    if not np.any(alpha):return base
    rgb=av.VideoFrame.from_ndarray(resize_rgb(replacement,(original.width,original.height)),format='rgb24')
    if fmt=='rgb24':patch=rgb
    else:
        matrix=original.colorspace if original.colorspace not in (0,2) else 5
        full_range=original.color_range==2 or (fmt.startswith('gray') and original.color_range==0)
        patch=rgb.reformat(format=fmt,dst_colorspace=matrix,dst_color_range='JPEG' if full_range else 'MPEG')
    out=av.VideoFrame(original.width,original.height,fmt)
    for source,generated,dest in zip(base.planes,patch.planes,out.planes):
        a=plane_array(source,fmt);b=plane_array(generated,fmt);d=plane_array(dest,fmt)
        weight=plane_mask(alpha,source.width,source.height)
        if fmt=='rgb24':weight=np.repeat(weight,3,axis=1)
        d[:]=np.rint(a.astype(np.float32)*(1-weight)+b.astype(np.float32)*weight).astype(d.dtype)
    out.colorspace=original.colorspace;out.color_range=2 if fmt.startswith('gray') and original.color_range==0 else original.color_range
    return out

def compose_lossless(source,patch,dest,meta,plan,fade,ffmpeg,interrupt=lambda:None,mask_path=None,settings=None):
    """Decode each original frame once; never framesync a rounded overlay."""
    intermediate=Path(dest).with_suffix('.video.nut');readers=[]
    try:
        gen=FrameReader(patch);readers.append(gen)
        mask=FrameReader(mask_path,plan['start']) if mask_path else None
        if mask:readers.append(mask)
        with av.open(str(source)) as src,av.open(str(intermediate),'w',format='nut') as out:
            s=src.streams.video[0];decoded=src.decode(s);first=next(decoded)
            fmt,codec=output_format(first)
            stream=out.add_stream(codec,rate=Fraction(meta['fps_ratio']));stream.width=s.width;stream.height=s.height;stream.pix_fmt=fmt
            stream.time_base=s.time_base;stream.codec_context.time_base=s.time_base;stream.options={'qp':'0','preset':'medium','bf':'0'}
            for key in ('color_range','colorspace','color_trc','color_primaries'):setattr(stream.codec_context,key,getattr(s.codec_context,key))
            # FFV1 gray has implicit full-range luma. x264 emits a neutral-chroma
            # YUV stream; signal that range or protected greys become darker.
            if fmt.startswith('gray') and stream.codec_context.color_range==0:stream.codec_context.color_range=2
            for i,frame in enumerate(itertools.chain((first,),decoded)):
                interrupt();stamp=frame.pts;tb=frame.time_base;second=float(frame.time)-meta['video_start']
                final=frame if frame.format.name==fmt else frame.reformat(format=fmt)
                if plan['start_frame']<=i<plan['end_frame']:
                    alpha=composite_mask(mask.at(second,nearest=True),settings) if mask else np.ones((s.height,s.width),np.float32)
                    alpha=resize_alpha(alpha,(s.width,s.height))
                    times=meta['frame_times'];next_time=times[i+1] if i+1<len(times) else meta['duration']
                    alpha*=fade_weight(second,plan,fade,next_time-second)
                    if np.any(alpha):final=blend_frame(frame,gen.at(second-plan['start'],nearest=True),alpha,fmt)
                final.pts=stamp;final.time_base=tb
                for packet in stream.encode(final):out.mux(packet)
            for packet in stream.encode():out.mux(packet)
        copy_audio=all(x in ('aac','mp3','alac','ac3','eac3') for x in meta['audio_codecs'])
        args=[ffmpeg(),'-hide_banner','-loglevel','error','-nostdin','-y','-copyts','-i',str(source),'-i',str(intermediate),
              '-map','1:v:0','-map','0:a?','-map_metadata','0','-map_chapters','0','-c:v','copy','-c:a','copy' if copy_audio else 'aac']
        if not copy_audio:args+=['-b:a','320k']
        args+=['-video_track_timescale',str(Fraction(meta.get('time_base','1/1000000')).denominator),'-movflags','+faststart',str(dest)]
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log)
            try:
                while process.poll() is None:interrupt();time.sleep(.1)
                if process.returncode:
                    log.seek(0);raise ValueError('Salvataggio finale fallito: '+log.read().decode(errors='replace')[-2500:])
            except BaseException:
                if process.poll() is None:process.kill();process.wait()
                raise
        return dict(audio_copied=copy_audio,fps=meta['fps'],width=meta['width'],height=meta['height'],
                    export_encoding='lossless_h264',source_planes_preserved=True,timing_version=2,
                    composite_mask_version=1,composite_mask_settings=composite_settings(settings) if mask else None)
    except BaseException:Path(dest).unlink(missing_ok=True);raise
    finally:
        intermediate.unlink(missing_ok=True)
        for reader in readers:reader.close()
