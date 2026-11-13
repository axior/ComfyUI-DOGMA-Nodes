"""Explicit original-size edit sampling choices, separate from frozen edit inputs."""
SAMPLING_KEYS=('turbo','turbo_strength','steps','sampler','scheduler','shift_video','shift_audio',
               'lying','lying_start','lying_end','native_shift','denoise')

def final_options(edit):
    return validate_final_options({'mode':edit.get('final_mode','match'),'steps':edit.get('final_steps',20),
                                   'method':edit.get('final_method','preserve'),'denoise':edit.get('final_denoise',.25),
                                   'output_dir':edit.get('final_output_dir',''),'resolution':edit.get('final_resolution','native'),
                                   'matte':{k:v for k,v in (edit.get('mask') or {}).items() if k.startswith('composite_')}})

def validate_final_options(value):
    value=value or {}
    mode=value.get('mode','match')
    if mode not in ('match','turbo','standard'):raise ValueError('Finale edit: scegli Come il provino, Turbo o Standard.')
    steps=float(value.get('steps',20))
    if not steps.is_integer() or not 1<=steps<=100:raise ValueError('Passaggi finale standard: un intero da 1 a 100.')
    method=value.get('method','preserve')
    if method not in ('guided','preserve','regenerate'):raise ValueError('Scegli come preparare il finale edit.')
    denoise=float(value.get('denoise',.25))
    if not .01<=denoise<=1:raise ValueError('Raffinamento finale: intensità tra 0,01 e 1.')
    directory=value.get('output_dir','')
    if not isinstance(directory,str):raise ValueError('Cartella finale non valida.')
    resolution=value.get('resolution','native')
    if resolution not in ('native','trial','source'):raise ValueError('Risoluzione H3: scegli nativa, provino o originale.')
    from .dogma_h3_edit_mask import mask_settings
    matte=mask_settings({**value.get('matte',{}),'enabled':True})
    return dict(mode=mode,steps=int(steps),method=method,denoise=denoise,output_dir=directory.strip(),resolution=resolution,
                matte={k:v for k,v in matte.items() if k.startswith('composite_')})

def generation_size(meta,edit,trial=False):
    import math
    w,h=meta['width'],meta['height']
    if trial or edit.get('final_resolution')=='trial':scale=min(1.,int(edit.get('trial_edge',512))/max(w,h))
    elif edit.get('final_resolution','native')=='source':scale=1.
    else:
        # Match native H3's 768-short-edge / 768*1344 canvas policy, while
        # preserving the source aspect and retaining small technical padding.
        ratio=w/h
        nw,nh=(768*ratio,768) if ratio>=1 else (768,768/ratio)
        factor=min(1.,math.sqrt((768*1344)/(nw*nh)))
        scale=min(1.,nw*factor/w,nh*factor/h)
    return max(2,round(w*scale/2)*2),max(2,round(h*scale/2)*2)

def is_ref_turbo(name):
    return str(name).replace('\\','/').split('/')[-1].startswith('minimax_h3_ref2v_turbo_')
