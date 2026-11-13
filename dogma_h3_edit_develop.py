"""Develop the approved edit, rather than silently regenerating its source."""
from pathlib import Path
import hashlib

def pack(value):
    import torch
    from comfy.nested_tensor import NestedTensor
    if isinstance(value,NestedTensor):return {'__dogma_nested__':[pack(x) for x in value.unbind()]}
    if isinstance(value,torch.Tensor):return value.detach().cpu().contiguous()
    if isinstance(value,dict):return {k:pack(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [pack(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise TypeError('Metadati latenti non supportati.')

def unpack(value):
    from comfy.nested_tensor import NestedTensor
    if isinstance(value,dict):
        if set(value)=={'__dogma_nested__'}:return NestedTensor([unpack(x) for x in value['__dogma_nested__']])
        return {k:unpack(v) for k,v in value.items()}
    if isinstance(value,list):return [unpack(x) for x in value]
    return value

def fingerprint(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def approved_movie(root,trial):
    path=Path(trial['saved_path']).resolve()
    if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
        raise ValueError('Video del provino scelto assente. Il sorgente non verrà usato al suo posto.')
    if trial.get('video_sha256') and fingerprint(path)!=trial['video_sha256']:
        raise ValueError('Il file del provino scelto è cambiato: finale annullato.')
    return path

def reference_movie(root,trial):
    path=trial.get('corrected_path')
    if not path:return approved_movie(root,trial)
    path=Path(path).resolve()
    if not path.is_relative_to(Path(root).resolve()) or not path.is_file():raise ValueError('Anteprima del provino recuperato non disponibile.')
    if trial.get('corrected_video_sha256') and fingerprint(path)!=trial['corrected_video_sha256']:raise ValueError('Anteprima recuperata modificata.')
    return path

def guide_latent(director,root,trial,vae,plate,width,height,read_trial,interrupt):
    import torch
    from comfy.nested_tensor import NestedTensor
    movie=approved_movie(root,trial)
    video_path=trial.get('latent')
    if video_path:
        path=(Path(root)/video_path).resolve()
        if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
            raise ValueError('Latenti del provino assenti. Rigenera il provino oppure scegli Mantieni edit.')
        if trial.get('latent_sha256') and fingerprint(path)!=trial['latent_sha256']:
            raise ValueError('Latenti del provino modificati: finale annullato.')
        saved=unpack(torch.load(path,map_location='cpu',weights_only=True))
        video=saved['samples'].unbind()[0]
        origin='saved_latent'
    else:
        # Older trials have only their video. Encode that approved result explicitly.
        frames=read_trial(reference_movie(root,trial))
        video=vae.encode(frames[:,:,:,:3]);del frames
        origin='encoded_legacy_trial'
    interrupt()
    if video.shape[-2:]!=(height//16,width//16):
        up=director.call('MinimaxH3LatentUpscaler3D',latent={'samples':video},
            model_name=trial['config']['finish']['upscaler'],
            mode={'mode':'target dimensions','width':width,'height':height},align=32,keep_proportion=False,
            device='cuda',precision='fp16',offload_after_upscale=True)[0]
        video=up['samples']
    target,audio=plate['samples'].unbind()
    if tuple(video.shape)!=tuple(target.shape):
        raise ValueError('Il provino scelto e il finale hanno griglie diverse. Nessuna rigenerazione dal sorgente eseguita.')
    out=plate.copy();video=video.to(device=target.device,dtype=target.dtype)
    if plate.get('noise_mask') is not None:
        vm,_=plate['noise_mask'].unbind();vm=vm.to(video)
        video=video*vm+target*(1-vm)
    out['samples']=NestedTensor((video,audio))
    return out,dict(method='guided',trial=trial['id'],input=origin,video_sha256=fingerprint(movie))
