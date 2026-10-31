"""DOGMA Director V2: persisted auditions and an explicit, resumable finish pipeline.

No network inference, model downloads or package installation. Native Comfy samplers
and installed H3 nodes do the work. The console is a separate browser dialog.
"""
import copy
import json
import re
import uuid
import os
import time
import threading
import shutil

_STATE_LOCK=threading.RLock()
from pathlib import Path


def defaults():
    return dict(version=2, session=str(uuid.uuid4()), action="draft", selected="", nonce=0,
        generate_audio=True, output_dir="", job="DOGMA", task="i2v", exploration="seeds", count=2, seed=64,
        prompt="", variants=[{"text":"", "loras":[]}], trial_loras={},
        first="", last="", refs=[], common_loras=[], seconds=5,
        auto_aspect=True, long_edge=512, width=512, height=288, sound=True,
        models={"i2v":"minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                "t2v":"minimax_h3_fl2va_pruned_int8_convrot.safetensors", "ref2v":"minimax_h3_ref2va_pruned_int8_convrot.safetensors", "clip":"qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "vae":"minimax_h3_video_vae_fp16.safetensors", "audio":"minimax_h3_audio_vae_fp32.safetensors"},
        draft={"turbo":"minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
               "turbo_strength":1., "steps":4, "sampler":"euler", "scheduler":"simple",
               "shift_video":12., "shift_audio":3., "lying":0., "lying_start":.1,"lying_end":.9},
        develop={"mode":"guided", "long_edge":960, "turbo":"", "turbo_strength":1.,
                 "steps":20, "sampler":"res_multistep", "scheduler":"simple", "denoise":.65,
                 "shift_video":12., "shift_audio":3., "lying":-.01, "lying_start":.1, "lying_end":.9},
        selected_development="",
        finish={"stages":"both", "resolution":"2k", "scale":2., "turbo":"",
                "turbo_strength":1., "sampler":"er_sde", "scheduler":"simple", "steps":8,
                "sigmas":"0.9035, 0.8000, 0.6316, 0.3158, 0.0000", "denoise":.35,
                "shift_video":12.,"shift_audio":3.,"lying":0.,"lying_start":.1,"lying_end":.9,
                "upscaler":"minimax_h3_latent_upscaler_3d_bf16.safetensors",
                "ultimate_scale":1., "tile_width":768,"tile_height":512,"tile_padding":64,
                "mask_blur":16,"ultimate_steps":8,"ultimate_denoise":.14,
                "ultimate_model":"minimax_h3_ref2va_pruned_int8_convrot.safetensors", "ultimate_sampler":"res_multistep", "ultimate_seed":42, "refine_seed":444,
                "ultimate_turbo":"minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                "ultimate_strength":1.},
        rife={"enabled":True,"fps":48,"model":"flownet.pkl","scale":1.,"batch_size":1,"fp16":True},
        preview={"enabled":True,"tiny_vae":"taeh3.safetensors","max_resolution":512,"frames":12,"fps":6})


def merge(base, value):
    out=copy.deepcopy(base)
    for k,v in value.items():
        out[k]=merge(out[k],v) if isinstance(v,dict) and isinstance(out.get(k),dict) else copy.deepcopy(v)
    return out


def parse_config(raw):
    data=json.loads(raw) if isinstance(raw,str) else copy.deepcopy(raw)
    if not isinstance(data,dict): raise ValueError("Configurazione Director non valida.")
    c=merge(defaults(),data)
    # Stored sampling settings always win. Restoring a preset is an explicit UI action.
    if c['finish']['resolution'] not in ('1k','2k','3k','4k'):
        raise ValueError('Risoluzione: scegli 1K, 2K, 3K o 4K.')
    c['session']=str(uuid.UUID(c['session']))
    if c['action'] not in ('draft','develop','finish'): raise ValueError('Azione non valida.')
    if c['task'] not in ('i2v','t2v','ref2v'): raise ValueError('Scegli I2V, T2V o Ref2Video.')
    if c['exploration'] not in ('seeds','prompts'): raise ValueError('Modalità provini non valida.')
    if not 1<=int(c['count'])<=10: raise ValueError('Scegli da 1 a 10 provini.')
    if not 0.2<=float(c['seconds'])<=15: raise ValueError('Durata: da 0,2 a 15 secondi.')
    if not 256<=int(c['long_edge'])<=1536: raise ValueError('Lato lungo provini: 256–1536 px.')
    for k in ('width','height'):
        if not 128<=int(c[k])<=2048: raise ValueError('Dimensioni provini fuori intervallo.')
    if not 1<=float(c['finish']['scale'])<=4 or not 1<=float(c['finish']['ultimate_scale'])<=4:
        raise ValueError('Fattore upscale: da 1 a 4.')
    if c['finish']['stages'] not in ('both','latent','ultimate'): raise ValueError('Finalizzazione non valida.')
    if int(c['rife']['fps']) not in (48,60): raise ValueError('RIFE: scegli 48 o 60 fps.')
    if not 1<=int(c['rife']['batch_size'])<=32: raise ValueError('RIFE batch: da 1 a 32.')
    if float(c['rife']['scale']) not in (.25,.5,1.,2.,4.): raise ValueError('Scala RIFE non valida.')
    if not 0<=int(c['seed'])<2**53: raise ValueError('Seed fuori intervallo.')
    if c['develop']['mode'] not in ('guided','native'): raise ValueError('Modalità sviluppo non valida.')
    if not 512<=int(c['develop']['long_edge'])<=1536: raise ValueError('Sviluppo: lato lungo 512–1536 px.')
    if not 0<float(c['develop']['denoise'])<1: raise ValueError('Sviluppo guidato: denoise maggiore di 0 e minore di 1.')
    for phase in ('draft','develop','finish'):
        s=c[phase]
        if not 0<=float(s['lying_start'])<=float(s['lying_end'])<=1: raise ValueError('Intervallo Lying Sigma non valido.')
        if not 1<=int(s['steps'])<=100: raise ValueError('Step: da 1 a 100.')
    for k in ('tile_width','tile_height'):
        if not 128<=int(c['finish'][k])<=2048 or int(c['finish'][k])%32: raise ValueError('Tasselli: multipli di 32, da 128 a 2048 px.')
    for k in ('denoise','ultimate_denoise'):
        if not 0<float(c['finish'][k])<=1: raise ValueError('Denoise: maggiore di 0 e massimo 1.')
    if len(c['refs'])>12: raise ValueError('Massimo 9 immagini e 3 video reference.')
    for kind,limit in [('image',9),('video',3)]:
        if sum(r.get('kind')==kind for r in c['refs'])>limit: raise ValueError(f'Troppe reference {kind}.')
    return c


def make_plan(c):
    common=c['prompt'].strip()
    if c['exploration']=='prompts':
        variants=c['variants']
        if not 1<=len(variants)<=10: raise ValueError('Inserisci da 1 a 10 schede prompt.')
        if any(not v.get('text','').strip() for v in variants): raise ValueError('Ogni scheda prompt deve contenere testo.')
        return [dict(prompt='\n\n'.join(x for x in (common,v['text'].strip()) if x),
                     seed=int(c['seed']),loras=c['common_loras']+v.get('loras',[])) for v in variants]
    if not common: raise ValueError('Scrivi il prompt prima di generare.')
    return [dict(prompt=common,seed=(int(c['seed'])+i)%(2**53-1),
                 loras=c['common_loras']+c['trial_loras'].get(str(i),[])) for i in range(int(c['count']))]


def dimensions(c, source=None):
    if c['auto_aspect'] and source:
        w,h=source
        s=int(c['long_edge'])/max(w,h)
        return max(128,round(w*s/32)*32),max(128,round(h*s/32)*32)
    return max(128,round(int(c['width'])/32)*32),max(128,round(int(c['height'])/32)*32)


def frames(seconds):
    n=max(5,round(float(seconds)*24))
    return n+(5-n)%17


def manifest_root(session):
    import folder_paths
    return Path(folder_paths.get_output_directory())/'DOGMA_H3_DIRECTOR'/str(uuid.UUID(session))


def write_json(path,value):
    # Serialize readers/writers; unique temporary names avoid competing executions.
    with _STATE_LOCK:
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            for attempt in range(8):
                try:
                    os.replace(temp,path)
                    break
                except PermissionError:
                    if attempt==7: raise
                    time.sleep(.025*(attempt+1))
        finally:
            try: temp.unlink(missing_ok=True)
            except OSError: pass


def state(session):
    with _STATE_LOCK:
        p=manifest_root(session)/'session.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'candidates':[], 'status':'new'}


def target_dimensions(w,h,resolution):
    edge={'1k':1024,'2k':2048,'3k':3072,'4k':4096}[resolution]
    return max(32,round(w/max(w,h)*edge/32)*32),max(32,round(h/max(w,h)*edge/32)*32)


def export_file(path,c):
    # Keep a Comfy preview copy; export to the requested folder without overwriting.
    if not c.get('output_dir','').strip(): return str(path.resolve())
    directory=Path(c['output_dir']).expanduser()
    if not directory.is_absolute(): raise ValueError('La cartella output deve avere un percorso assoluto.')
    directory.mkdir(parents=True,exist_ok=True)
    dest=directory/(path.stem+'_'+uuid.uuid4().hex[:8]+path.suffix)
    shutil.copy2(path,dest)
    return str(dest.resolve())


def call(name,uid='dogma',**kwargs):
    import nodes
    cls=nodes.NODE_CLASS_MAPPINGS.get(name)
    if cls is None: raise ValueError(f'Nodo richiesto non disponibile: {name}. Installalo o aggiornalo dal Manager.')
    if hasattr(cls,'PREPARE_CLASS_CLONE'):
        return cls.PREPARE_CLASS_CLONE({'hidden_inputs':{'UNIQUE_ID':str(uid)}}).execute(**kwargs)
    return getattr(cls(),cls.FUNCTION)(**kwargs)


def input_file(name):
    import folder_paths
    # Only input assets uploaded through Comfy, never arbitrary server paths.
    root=Path(folder_paths.get_input_directory()).resolve()
    p=(root/name).resolve()
    if not p.is_relative_to(root) or not p.is_file(): raise ValueError(f'File input non disponibile: {Path(name).name}')
    return p


def load_image(name):
    import nodes
    input_file(name)
    return nodes.LoadImage().load_image(name)[0][:1]


def video_frames(name, long_edge, seconds):
    import av, numpy as np, torch
    from PIL import Image
    out=[]; next_time=0.; first_time=None; max_frames=frames(min(seconds,15))
    with av.open(str(input_file(name))) as v:
        stream=v.streams.video[0]
        fps=float(stream.average_rate or 24)
        for i,f in enumerate(v.decode(stream)):
            import comfy.model_management
            comfy.model_management.throw_exception_if_processing_interrupted()
            t=float(f.time) if f.time is not None else i/fps
            if first_time is None: first_time=t
            t-=first_time
            if t+1e-6<next_time: continue
            im=f.to_image(); w,h=im.size; s=min(1.,long_edge/max(w,h))
            im=im.resize((max(32,round(w*s/32)*32),max(32,round(h*s/32)*32)),Image.Resampling.LANCZOS)
            tensor=torch.from_numpy(np.array(im).astype(np.float32)/255.)
            while next_time<=t+1e-6 and len(out)<max_frames:
                out.append(tensor); next_time+=1/24
            if len(out)>=max_frames: break
    if len(out)<5: raise ValueError('Il video reference deve contenere almeno 5 fotogrammi a 24 fps.')
    return torch.stack(out)


def assets(c):
    a={'first':None,'last':None,'images':{},'videos':{}}
    if c['task']=='i2v':
        if not c['first'] and not c['last']: raise ValueError('Carica il primo o l’ultimo fotogramma.')
        for k in ('first','last'):
            if c[k]: a[k]=load_image(c[k])
    if c['task']=='ref2v':
        if not c['refs']: raise ValueError('Carica almeno una reference.')
        for r in c['refs']:
            if r['kind']=='image': a['images'][f"ref_image_{len(a['images'])+1}"]=load_image(r['name'])
            elif r['kind']=='video': a['videos'][f"ref_video_{len(a['videos'])+1}"]=video_frames(r['name'],c['long_edge'],c['seconds'])
            else: raise ValueError('Tipo reference non valido.')
    return a


def condition(c,a,res,prompt,w,h,n):
    from comfy_extras.nodes_minimax_h3 import MiniMaxH3ImageToVideo,MiniMaxH3ReferenceToVideo
    if c['task']=='ref2v':
        return MiniMaxH3ReferenceToVideo.execute(res['clip'],prompt,w,h,n,'match',
            vae=res['vae'],audio_vae=res['audio'],ref_images=a['images'],ref_videos=a['videos'])
    return MiniMaxH3ImageToVideo.execute(res['clip'],res['vae'],prompt,w,h,n,a['first'],a['last'])


def load_resources(c):
    import nodes
    m=c['models']; name=m[c['task']]
    if not name: raise ValueError(f'Seleziona il modello {c["task"]} nelle impostazioni avanzate.')
    return {'model':nodes.UNETLoader().load_unet(name,'default')[0],
            'clip':nodes.CLIPLoader().load_clip(m['clip'],'minimax','default')[0],
            'vae':nodes.VAELoader().load_vae(m['vae'])[0],
            'audio':nodes.VAELoader().load_vae(m['audio'])[0]}


def prepare_model(res,c,trial,phase,uid):
    import nodes
    from comfy_extras.nodes_minimax_h3 import MiniMaxH3SigmaShift
    s=c[phase]; model=res['model']
    stack=list(trial['loras'])
    if s.get('turbo'): stack.append({'name':s['turbo'],'strength':s['turbo_strength']})
    for l in stack:
        if l.get('name') and l.get('enabled',True) and float(l.get('strength',1))!=0:
            model=nodes.LoraLoaderModelOnly().load_lora_model_only(model,l['name'],float(l.get('strength',1)))[0]
    if not s.get('native_shift',False):
        model=MiniMaxH3SigmaShift.execute(model,float(s['shift_video']),float(s['shift_audio']))[0]
    p=c['preview']
    if p['enabled']:
        model=call('ModelPreviewOverrideKJ',uid,model=model,max_resolution=int(p['max_resolution']),
            jpeg_quality=75,suppress_default_preview=True,preview_frames=int(p['frames']),preview_fps=int(p['fps']),
            tiny_vae=p['tiny_vae'],vae=res['vae'])[0]
    return model


def sampler_for(s):
    import comfy.samplers
    if s['sampler'] not in comfy.samplers.KSampler.SAMPLERS: raise ValueError('Sampler non disponibile: '+s['sampler'])
    sampler=comfy.samplers.sampler_object(s['sampler'])
    if float(s['lying'])!=0:
        sampler=call('LyingSigmaSampler',sampler=sampler,dishonesty_factor=float(s['lying']),
                     start_percent=float(s['lying_start']),end_percent=float(s['lying_end']))[0]
    return sampler


def sample(model,cond,latent,s,seed,manual=False,progress=None):
    import torch
    from comfy_extras.nodes_custom_sampler import BasicScheduler,Guider_Basic,Noise_RandomNoise,SamplerCustomAdvanced
    guider=Guider_Basic(model); guider.set_conds(cond)
    if manual and s.get('sigmas','').strip():
        vals=[float(x.strip()) for x in s['sigmas'].split(',')]
        if len(vals)<2 or vals[-1]!=0 or any(a<=b for a,b in zip(vals,vals[1:])): raise ValueError('Sigma manuali: valori decrescenti, ultimo 0.')
        sigmas=torch.tensor(vals,dtype=torch.float32)
    else: sigmas=BasicScheduler.execute(model,s['scheduler'],int(s['steps']),float(s.get('denoise',1)))[0]
    if progress is None:
        return SamplerCustomAdvanced.execute(Noise_RandomNoise(seed),guider,sampler_for(s),sigmas,latent)[0]
    import comfy.sample, comfy.utils, comfy.model_management, latent_preview
    latent=latent.copy()
    tensor=comfy.sample.fix_empty_latent_channels(model,latent['samples'],latent.get('downscale_ratio_spacial'),latent.get('downscale_ratio_temporal'))
    latent['samples']=tensor
    preview=latent_preview.prepare_callback(model,len(sigmas)-1,{})
    def callback(step,x0,x,total):
        if preview: preview(step,x0,x,total)
        progress(step+1,total)
    noise=Noise_RandomNoise(seed).generate_noise(latent)
    if s.get('lock_audio'):
        from comfy.nested_tensor import NestedTensor
        video,audio=tensor.unbind(); nv,na=noise.unbind()
        noise=NestedTensor([nv,torch.zeros_like(na)])
        latent['noise_mask']=NestedTensor([torch.ones_like(video),torch.zeros_like(audio)])
    result=guider.sample(noise,tensor,sampler_for(s),sigmas,
        denoise_mask=latent.get('noise_mask'),callback=callback,
        disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,seed=seed)
    if s.get('lock_audio'):
        result=NestedTensor([result.unbind()[0],audio.to(result.unbind()[1].device)])
    latent['samples']=result.to(comfy.model_management.intermediate_device())
    latent.pop('downscale_ratio_spacial',None);latent.pop('downscale_ratio_temporal',None)
    return latent


def decode(res,latent,generate_audio=True):
    import nodes
    from comfy_extras.nodes_audio import VAEDecodeAudio
    return nodes.VAEDecode().decode(res['vae'],latent)[0],(VAEDecodeAudio.execute(res['audio'],latent)[0] if generate_audio else None)


def rife_preflight(settings):
    """Fail before inference, rather than let the third-party node download weights."""
    import nodes, folder_paths, inspect
    cls=nodes.NODE_CLASS_MAPPINGS.get('RIFEInterpolation')
    if cls is None: raise ValueError('RIFE richiede ComfyUI-VFI. Installalo dal Manager oppure disattiva RIFE in Finalizza.')
    name=settings['model']
    if Path(name).name!=name or name!='flownet.pkl': raise ValueError('Modello RIFE non valido: usa flownet.pkl.')
    base=Path(inspect.getfile(cls)).parent
    paths=[base/'rife'/'train_log'/name,Path(folder_paths.models_dir)/'rife'/name,base/'models'/name]
    if not any(p.is_file() for p in paths):
        raise ValueError('Pesi RIFE flownet.pkl assenti. Configura ComfyUI-VFI o disattiva RIFE; nessun download automatico è stato avviato.')


def save_video(images,audio,path,metadata,fps=24):
    from comfy_extras.nodes_video import CreateVideo
    from comfy_api.latest import Types
    path.parent.mkdir(parents=True,exist_ok=True)
    video=CreateVideo.execute(images,float(fps),audio)[0]
    video.save_to(str(path),format=Types.VideoContainer('mp4'),codec=Types.VideoCodec('h264'),metadata={'dogma':metadata},crf=20)


def view_file(p):
    import folder_paths
    rel=p.relative_to(Path(folder_paths.get_output_directory()))
    return {'filename':rel.name,'subfolder':rel.parent.as_posix(),'type':'output'}


class DOGMAH3DirectorConsoleV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'config':('STRING',{'default':json.dumps(defaults()),'multiline':True})}}
    RETURN_TYPES=('DOGMA_H3_CONFIG',)
    RETURN_NAMES=('sessione',)
    FUNCTION='run'
    CATEGORY='DOGMA/H3 Director'
    def run(self,config): return (parse_config(config),)


class DOGMAH3DirectorEngineV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'sessione':('DOGMA_H3_CONFIG',)},'hidden':{'unique_id':'UNIQUE_ID'}}
    RETURN_TYPES=('STRING',)
    RETURN_NAMES=('stato',)
    FUNCTION='run'
    OUTPUT_NODE=True
    CATEGORY='DOGMA/H3 Director/Advanced'
    @classmethod
    def IS_CHANGED(cls,**kwargs): return float('nan')

    def run(self,sessione,unique_id=None):
        import torch
        from .dogma_h3_director_v133 import pack,unpack
        c=parse_config(sessione); root=manifest_root(c['session']); root.mkdir(parents=True,exist_ok=True)
        st=state(c['session']); st['engine']=str(unique_id); st['session']=c['session']
        def update(status,message,**extra):
            from server import PromptServer
            st.update(status=status,message=message,action=c['action'],progress=None,**extra)
            write_json(root/'session.json',st)
            PromptServer.instance.send_sync('dogma.h3.v2',st)
        def progress(step,total):
            from server import PromptServer
            st['progress']={'step':step,'total':total}
            PromptServer.instance.send_sync('dogma.h3.v2.progress',{'session':c['session'],'engine':str(unique_id),'step':step,'total':total})
        try:
            update('running','Preparazione risorse…')
            if c['action']=='draft':
                plan=make_plan(c); a=assets(c)
                first=next((x for x in [a['first'],a['last'],*a['images'].values(),*a['videos'].values()] if x is not None),None)
                w,h=dimensions(c,(first.shape[2],first.shape[1]) if first is not None else None)
                n=frames(c['seconds']); res=load_resources(c)
                run=str(uuid.uuid4()); dest=root/run; dest.mkdir()
                update('running','Preparazione prompt…',candidates=[],developments=[],finals=[],run=run,width=w,height=h,frames=n,total_trials=len(plan))
                # Encode once for shared prompts; different prompt cards preserve all paragraphs.
                encoded={}
                for i,p in enumerate(plan):
                    if p['prompt'] not in encoded:
                        update('running',f'Provino {i+1}/{len(plan)} · preparazione prompt')
                        encoded.clear()
                        encoded[p['prompt']]=condition(c,a,res,p['prompt'],w,h,n)
                    update('running',f'Provino {i+1}/{len(plan)} · generazione',active=i+1)
                    cond,lat=encoded[p['prompt']][0],encoded[p['prompt']][1]
                    model=prepare_model(res,c,p,'draft',unique_id)
                    result=sample(model,cond,lat,c['draft'],p['seed'],progress=progress)
                    cid=str(uuid.uuid4()); latent_path=dest/(cid+'.pt')
                    torch.save(pack(result),latent_path)
                    update('running',f'Provino {i+1}/{len(plan)} · decodifica')
                    images,audio=decode(res,result,c['generate_audio'])
                    job=re.sub(r'[^\w.-]+','_',c['job'])[:80] or 'DOGMA'
                    movie=dest/(job+f'_H3_PROVINO_{i+1:02}_{cid[:8]}.mp4'); save_video(images,audio,movie,p)
                    candidate=dict(id=cid,label=f'Provino {i+1:02}',video=view_file(movie),
                        saved_path=export_file(movie,c),latent=f'{run}/{cid}.pt',width=w,height=h,frames=n,config=copy.deepcopy(c),**p)
                    st['candidates'].append(candidate)
                    update('running',f'Provino {i+1}/{len(plan)} pronto')
                    del result,images,audio,model
                update('ready','Bozze pronte. Scegli quale sviluppare in qualità.',active=None)
            elif c['action']=='develop':
                candidate=next((p for p in st.get('candidates',[]) if p['id']==c['selected']),None)
                if candidate is None: raise ValueError('Scegli una bozza da sviluppare.')
                frozen=parse_config(candidate['config']); frozen['develop']=copy.deepcopy(c['develop']); frozen['preview']=c['preview']
                # No Turbo from the draft is inherited. Only the chosen additional LoRAs persist.
                d=frozen['develop']; frozen['long_edge']=int(d['long_edge'])
                res=load_resources(frozen); a=assets(frozen)
                w,h=dimensions(dict(auto_aspect=True,long_edge=d['long_edge']), (candidate['width'],candidate['height']))
                n=candidate['frames']; folder=root/'developments'/str(uuid.uuid4()); folder.mkdir(parents=True)
                update('running','Sviluppo · preparazione alla risoluzione di qualità')
                cond,empty=condition(frozen,a,res,candidate['prompt'],w,h,n)
                settings=copy.deepcopy(d)
                if d['mode']=='guided':
                    from comfy.nested_tensor import NestedTensor
                    path=(root/candidate['latent']).resolve()
                    if not path.is_relative_to(root.resolve()): raise ValueError('Percorso latenti non valido.')
                    saved=unpack(torch.load(path,map_location='cpu',weights_only=True))
                    video,audio_lat=saved['samples'].unbind()
                    update('running','Sviluppo · trasferimento dei latenti della bozza scelta')
                    up=call('MinimaxH3LatentUpscaler3D',latent={'samples':video},model_name=c['finish']['upscaler'],
                        mode={'mode':'target dimensions','width':w,'height':h},align=32,keep_proportion=False,
                        device='cuda',precision='fp16',offload_after_upscale=True)[0]
                    v=up['samples']; h,w=v.shape[-2]*16,v.shape[-1]*16
                    if tuple(v.shape)!=tuple(empty['samples'].unbind()[0].shape):
                        cond,empty=condition(frozen,a,res,candidate['prompt'],w,h,n)
                    expected_video,expected_audio=empty['samples'].unbind()
                    if tuple(v.shape)!=tuple(expected_video.shape) or tuple(audio_lat.shape)!=tuple(expected_audio.shape):
                        raise ValueError('Dimensioni dei latenti incompatibili con lo sviluppo. Rigenera la bozza con la stessa durata e modalità.')
                    latent={'samples':NestedTensor([v,audio_lat])}; settings['lock_audio']=True
                else:
                    latent=empty; settings['denoise']=1.
                model=prepare_model(res,frozen,candidate,'develop',unique_id)
                update('running','Sviluppo · campionamento di qualità',active='develop')
                started=time.monotonic()
                result=sample(model,cond,latent,settings,candidate['seed'],progress=progress)
                torch.save(pack(result),folder/'developed.pt')
                update('running','Sviluppo · decodifica e salvataggio')
                images,audio=decode(res,result,c['generate_audio'])
                job=re.sub(r'[^\w.-]+','_',c['job'])[:80] or 'DOGMA'
                movie=folder/(job+'_H3_SVILUPPO.mp4'); save_video(images,audio,movie,candidate)
                item=dict(id=uuid.uuid4().hex,candidate=candidate['id'],label=candidate['label']+' · sviluppo',
                    video=view_file(movie),saved_path=export_file(movie,c),latent=str((folder/'developed.pt').relative_to(root)),
                    width=images.shape[2],height=images.shape[1],frames=n,config=frozen,mode=d['mode'],
                    elapsed_seconds=round(time.monotonic()-started,2),prompt=candidate['prompt'],seed=candidate['seed'],loras=candidate['loras'])
                st.setdefault('developments',[]).append(item)
                update('developed','Sviluppo pronto. Controllalo e scegli quale finalizzare.',active=None)
            else:
                candidate=next((p for p in st.get('developments',[]) if p['id']==c.get('selected_development') and p['candidate']==c['selected']),None)
                if candidate is None: raise ValueError('Sviluppa prima la bozza e seleziona uno sviluppo disponibile.')
                if c['rife']['enabled']: rife_preflight(c['rife'])
                # Freeze source/prompt/model/LoRAs to selected trial; only finishing controls are editable.
                frozen=parse_config(candidate['config']); frozen['finish']=c['finish']; frozen['preview']=c['preview']
                res=load_resources(frozen); a=assets(frozen)
                path=(root/candidate['latent']).resolve()
                if not path.is_relative_to(root.resolve()): raise ValueError('Percorso latenti non valido.')
                latent=unpack(torch.load(path,map_location='cpu',weights_only=True))
                fin=c['finish']; stages=fin['stages']; w,h=candidate['width'],candidate['height']; n=candidate['frames']
                target_w,target_h=target_dimensions(w,h,fin['resolution'])
                folder=root/'finals'/str(uuid.uuid4()); folder.mkdir(parents=True)
                job=re.sub(r'[^\w.-]+','_',c['job'])[:80] or 'DOGMA'
                if stages in ('both','latent'):
                    from comfy.nested_tensor import NestedTensor
                    update('running','Finalizzazione · upscale dei latenti')
                    video,audio_lat=latent['samples'].unbind()
                    latent_w,latent_h=(target_w,target_h) if stages=='latent' else target_dimensions(w,h,fin['resolution'])
                    if stages=='both' and max(latent_w,latent_h)>max(w,h)*2:
                        latent_w,latent_h=round(w*2/32)*32,round(h*2/32)*32
                    latent_w,latent_h=max(w,latent_w),max(h,latent_h)
                    up=call('MinimaxH3LatentUpscaler3D',latent={'samples':video},model_name=fin['upscaler'],
                        mode={'mode':'target dimensions','width':latent_w,'height':latent_h},align=32,keep_proportion=False,
                        device='cuda',precision='fp16',offload_after_upscale=True)[0]
                    latent={'samples':NestedTensor([up['samples'],audio_lat])}
                    h,w=up['samples'].shape[-2]*16,up['samples'].shape[-1]*16
                    cond=condition(frozen,a,res,candidate['prompt'],w,h,n)[0]
                    model=prepare_model(res,frozen,candidate,'finish',unique_id)
                    update('running','Finalizzazione · raffinamento dei latenti')
                    latent=sample(model,cond,latent,dict(fin,lock_audio=True),int(fin['refine_seed']),True,progress=progress)
                    torch.save(pack(latent),folder/'latent_refined.pt')
                update('running','Finalizzazione · decodifica')
                images,audio=decode(res,latent,c['generate_audio'])
                if stages=='latent' and tuple(images.shape[1:3])!=(target_h,target_w):
                    import torch.nn.functional as F
                    images=torch.cat([F.interpolate(chunk.movedim(-1,1),size=(target_h,target_w),mode='bicubic',align_corners=False).movedim(1,-1).clamp(0,1) for chunk in images.split(8)])
                intermediate=folder/(job+'_H3_LATENT.mp4' if stages!='ultimate' else job+'_H3_SCELTO.mp4')
                save_video(images,audio,intermediate,candidate)
                st.setdefault('finals',[]).append({'label':'Intermedio · Latent' if stages!='ultimate' else 'Intermedio · Provino scelto','candidate':candidate['id'],'video':view_file(intermediate),'saved_path':export_file(intermediate,c),'id':uuid.uuid4().hex,'fps':24,'frames':len(images),'width':images.shape[2],'height':images.shape[1]})
                update('running','Passaggio a 24 fps salvato')
                fps=24
                if c['rife']['enabled']:
                    r=c['rife']; fps=int(r['fps'])
                    update('running',f'Finalizzazione · RIFE da 24 a {fps} fps, prima di Ultimate')
                    images=call('RIFEInterpolation',unique_id,images=images,source_fps=24,target_fps=fps,
                        scale=float(r['scale']),model_name=r['model'],batch_size=int(r['batch_size']),use_fp16=bool(r['fp16']))[0]
                    out=folder/(job+f'_H3_RIFE_{fps}fps.mp4')
                    save_video(images,audio,out,candidate,fps=fps)
                    st['finals'].append({'label':f'Intermedio · RIFE · {fps} fps','candidate':candidate['id'],'video':view_file(out),
                        'saved_path':export_file(out,c),'id':uuid.uuid4().hex,'fps':fps,'frames':len(images),'width':images.shape[2],'height':images.shape[1]})
                if stages in ('both','ultimate'):
                    import torch.nn.functional as F
                    from comfy_extras.nodes_custom_sampler import Guider_Basic,BasicScheduler
                    update('running','Finalizzazione · Ultimate a tasselli')
                    w,h=target_w,target_h
                    if (h,w)!=tuple(images.shape[1:3]):
                        images=torch.cat([F.interpolate(chunk.movedim(-1,1),size=(h,w),mode='bicubic',align_corners=False).movedim(1,-1).clamp(0,1) for chunk in images.split(8)])
                    # Original Ultimate H3 workflow appends a temporal context tail, then trims it.
                    count=len(images); padded_n=frames((count+17)/24)
                    padded=torch.cat([images,images[-1:].repeat(padded_n-count,1,1,1)])
                    # Ultimate encodes its own local video tiles. Full-frame keyframe
                    # tokens cannot be passed to a tile-sized latent (H3 shape mismatch).
                    # Match the original Ultimate graph: FL2V text conditioning only.
                    import nodes
                    ultimate_res=dict(res)
                    if fin['ultimate_model']!=frozen['models'][frozen['task']]:
                        ultimate_res['model']=nodes.UNETLoader().load_unet(fin['ultimate_model'],'default')[0]
                    ultimate_config=copy.deepcopy(frozen)
                    ultimate_config['finish']['turbo']=fin['ultimate_turbo']
                    ultimate_config['finish']['turbo_strength']=fin['ultimate_strength']
                    ultimate_config['finish']['native_shift']=True
                    model=prepare_model(ultimate_res,ultimate_config,dict(candidate,loras=[]),'finish',unique_id)
                    from comfy_extras.nodes_minimax_h3 import MiniMaxH3ImageToVideo
                    cond=MiniMaxH3ImageToVideo.execute(res['clip'],res['vae'],candidate['prompt'],w,h,padded_n,None,None)[0]
                    guider=Guider_Basic(model); guider.set_conds(cond)
                    sigmas=BasicScheduler.execute(model,fin['scheduler'],int(fin['ultimate_steps']),float(fin['ultimate_denoise']))[0]
                    images=call('UltimateSDUpscaleNoUpscaleGuider',unique_id,upscaled_image=padded,guider=guider,sampler=sampler_for(dict(fin,sampler=fin['ultimate_sampler'],lying=0)),sigmas=sigmas,
                        vae=res['vae'],seed=int(fin['ultimate_seed']),mode_type='Chess',tile_width=int(fin['tile_width']),tile_height=int(fin['tile_height']),
                        mask_blur=int(fin['mask_blur']),tile_padding=int(fin['tile_padding']),seam_fix_mode='None',seam_fix_denoise=.15,
                        seam_fix_mask_blur=8,seam_fix_width=64,seam_fix_padding=16,tile_overlap_mode='Reprocess Overlap',tiled_decode=True,batch_size=1,anchor_context=False)[0][:count]
                    out=folder/(job+f'_H3_ULTIMATE_{fps}fps.mp4')
                    save_video(images,audio,out,candidate,fps=fps)
                    st['finals'].append({'label':f'Ultimate · {fps} fps','candidate':candidate['id'],'video':view_file(out),'saved_path':export_file(out,c),'id':uuid.uuid4().hex,'fps':fps,'frames':len(images),'width':images.shape[2],'height':images.shape[1]})
                st['finals'][-1]['label']='Finale · '+st['finals'][-1]['label'].removeprefix('Intermedio · ')
                st['finals'][-1]['complete']=True
                update('done','Finalizzazione completata. I passaggi sono salvati.',active=None)
            return {'ui':{'dogma_v2':[st]},'result':(st['message'],)}
        except Exception as exc:
            try: update('error',str(exc),active=None)
            except Exception: pass  # Preserve the actual inference or storage error.
            raise


class DOGMAH3DirectorStatusV2:
    @classmethod
    def INPUT_TYPES(cls): return {'required':{'stato':('STRING',{'forceInput':True})}}
    RETURN_TYPES=()
    FUNCTION='run'
    OUTPUT_NODE=True
    CATEGORY='DOGMA/H3 Director/Advanced'
    def run(self,stato): return {'ui':{'text':[stato]}}


NODE_CLASS_MAPPINGS={'DOGMAH3DirectorConsoleV2':DOGMAH3DirectorConsoleV2,'DOGMAH3DirectorEngineV2':DOGMAH3DirectorEngineV2,'DOGMAH3DirectorStatusV2':DOGMAH3DirectorStatusV2}
NODE_DISPLAY_NAME_MAPPINGS={'DOGMAH3DirectorConsoleV2':'DOGMA / H3 Director · APRI STUDIO','DOGMAH3DirectorEngineV2':'DOGMA / H3 Engine V2','DOGMAH3DirectorStatusV2':'DOGMA / Stato sessione'}


def register_routes():
    from server import PromptServer
    from aiohttp import web
    import folder_paths, comfy.samplers, nodes
    routes=PromptServer.instance.routes
    def local_request(request):
        from urllib.parse import urlparse
        if request.remote not in ('127.0.0.1','::1'):
            raise web.HTTPForbidden(text='Disponibile solo sul computer Comfy.')
        origin=request.headers.get('Origin')
        if origin and urlparse(origin).netloc!=request.host:
            raise web.HTTPForbidden(text='Origine non valida.')

    @routes.post('/dogma/h3/v2/open-folder')
    async def open_folder(request):
        local_request(request)
        import asyncio
        data=await request.json(); st=await asyncio.to_thread(state,data['session'])
        item=next((x for x in st.get('finals',[])+st.get('developments',[])+st.get('candidates',[]) if x.get('id')==data.get('id')),None)
        if not item or not item.get('saved_path'): raise web.HTTPNotFound(text='Risultato non disponibile.')
        directory=Path(item['saved_path']).parent
        if not directory.is_dir(): raise web.HTTPNotFound(text='Cartella non disponibile.')
        if os.name!='nt': raise web.HTTPBadRequest(text='Apri cartella richiede Windows.')
        os.startfile(str(directory))
        return web.json_response({'ok':True})

    @routes.post('/dogma/h3/v2/choose-folder')
    async def choose_folder(request):
        local_request(request)
        raise web.HTTPGone(text='Aggiorna il pannello DOGMA: la scelta cartella ora avviene nel browser.')

    @routes.get('/dogma/h3/v2/folders')
    async def folders(request):
        local_request(request)
        import asyncio
        def browse():
            directory=Path(request.query.get('path') or folder_paths.get_output_directory()).expanduser().resolve()
            if not directory.is_dir(): raise ValueError('Cartella inesistente. Inserisci un percorso valido.')
            directories=[]
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(): directories.append({'name':entry.name,'path':entry.path})
                    except OSError: continue
                    if len(directories)>500: break
            directories.sort(key=lambda x:x['name'].casefold())
            drives=[]
            if os.name=='nt':
                import ctypes
                bits=ctypes.windll.kernel32.GetLogicalDrives()
                drives=[{'name':chr(65+i)+':','path':chr(65+i)+':/'} for i in range(26) if bits & (1<<i)]
            return {'path':str(directory),'parent':str(directory.parent) if directory.parent!=directory else None,
                    'drives':drives,'directories':directories[:500],'truncated':len(directories)>500}
        try: return web.json_response(await asyncio.to_thread(browse))
        except (ValueError,OSError) as exc: raise web.HTTPBadRequest(text=str(exc))

    def build_catalog():
        def files(k):
            try: return folder_paths.get_filename_list(k)
            except KeyError: return []
        return {'defaults':defaults(),'models':files('diffusion_models'),'clip':files('text_encoders'),
            'vae':files('vae'),'tiny_vae':['none']+files('vae_approx'),'loras':files('loras'),'upscalers':files('latent_upscale_models'),
            'samplers':comfy.samplers.KSampler.SAMPLERS,'schedulers':comfy.samplers.KSampler.SCHEDULERS,
            'nodes':list(nodes.NODE_CLASS_MAPPINGS)}
    catalog_task=None
    catalog_time=0
    @routes.get('/dogma/h3/v2/catalog')
    async def catalog(request):
        import asyncio,time
        nonlocal catalog_task,catalog_time
        if catalog_task is None or (catalog_task.done() and (catalog_task.exception() is not None or time.monotonic()-catalog_time>30)):
            catalog_time=time.monotonic()
            catalog_task=asyncio.create_task(asyncio.to_thread(build_catalog))
        return web.json_response(await asyncio.shield(catalog_task))

    @routes.get('/dogma/h3/v2/session/{session}')
    async def session(request):
        import asyncio
        try: return web.json_response(await asyncio.to_thread(state,request.match_info['session']))
        except (ValueError,OSError): return web.json_response({'error':'Sessione non disponibile'},status=400)


try:
    register_routes()
except (ImportError,AttributeError):
    pass  # Offline validation; routes are registered when Comfy imports the extension.
