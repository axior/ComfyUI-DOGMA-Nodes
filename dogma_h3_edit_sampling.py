"""Explicit original-size edit sampling choices, separate from frozen edit inputs."""
SAMPLING_KEYS=('turbo','turbo_strength','steps','sampler','scheduler','shift_video','shift_audio',
               'lying','lying_start','lying_end','native_shift','denoise')

def final_options(edit):
    return validate_final_options({'mode':edit.get('final_mode','match'),'steps':edit.get('final_steps',20),
                                   'method':edit.get('final_method','preserve'),'denoise':edit.get('final_denoise',.25),
                                   'output_dir':edit.get('final_output_dir','')})

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
    return dict(mode=mode,steps=int(steps),method=method,denoise=denoise,output_dir=directory.strip())

def is_ref_turbo(name):
    return str(name).replace('\\','/').split('/')[-1].startswith('minimax_h3_ref2v_turbo_')
