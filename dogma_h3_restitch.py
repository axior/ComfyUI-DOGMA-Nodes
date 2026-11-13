"""Shared preview atlas and CPU-only, in-place restitch of a completed edit."""
from pathlib import Path
from fractions import Fraction
import asyncio,copy,hashlib,json,math,os,shutil,time,uuid
import av
import numpy as np
from scipy.ndimage import distance_transform_edt
from .dogma_h3_edit_mask import FrameReader,processed_mask,mask_settings,composite_settings,validate_alignment
from .dogma_h3_edit_develop import fingerprint

def inputs(core,session,item_id):
    st=core.state(session);root=core.manifest_root(session).resolve()
    item=next((x for x in st.get('edits',[]) if x.get('id')==item_id and x.get('complete')),None)
    if not item:raise ValueError('Video completo non disponibile.')
    c=item['config'];settings=mask_settings(c['edit'].get('mask'))
    if not settings['enabled']:raise ValueError('Le varianti di restitch richiedono una maschera video.')
    relative=item.get('raw_patch');sha=item.get('raw_patch_sha256')
    if not relative:
        trial=next((x for x in st.get('edit_trials',[]) if x.get('id')==item.get('trial')),None)
        if item.get('development',{}).get('method')=='preserve' and trial:
            relative=trial.get('raw_patch');sha=trial.get('raw_patch_sha256')
    if not relative:raise ValueError('Questo finale precedente non conserva il tratto generato necessario. Preparalo di nuovo dal provino con i nodi aggiornati; nessuna sostituzione con il video originale.')
    raw=(root/relative).resolve()
    if not raw.is_relative_to(root) or not raw.is_file():raise ValueError('Tratto generato non disponibile per il restitch.')
    f=item['video'];master=(root.parent.parent/f.get('subfolder','')/f['filename']).resolve()
    if not master.is_relative_to(root) or not master.is_file():raise ValueError('Master della sessione non disponibile.')
    return st,item,root,core.input_file(c['edit']['source']),core.input_file(settings['source']),raw,master,sha

def preview_atlas(core,session,item_id,edge=320):
    from .dogma_h3_video_edit import cached_probe,plan_interval
    import folder_paths
    if edge not in (320,960):raise ValueError('Risoluzione anteprima non disponibile.')
    st,item,root,source,mask,raw,master,sha=inputs(core,session,item_id)
    meta=cached_probe(source);validate_alignment(meta,cached_probe(mask));e=item['config']['edit'];plan=plan_interval(meta,e['start'],e['end'])
    marks=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in (source,mask,raw)]
    key=hashlib.sha256(json.dumps([marks,plan,'atlas-v2-'+str(edge)],sort_keys=True).encode()).hexdigest()
    folder=Path(folder_paths.get_temp_directory())/'DOGMA_RESTITCH';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(key+'.mp4');ratio=min(1.,edge/max(meta['width'],meta['height']))
    w,h=(max(2,round(meta[k]*ratio/2)*2) for k in ('width','height'))
    field_range=256.;started=time.monotonic()
    if not path.exists():
        if sha and fingerprint(raw)!=sha:raise ValueError('Il tratto generato è stato modificato.')
        readers=[];temp=path.with_name(key+'.'+uuid.uuid4().hex+'.mp4')
        try:
            src=FrameReader(source,plan['start']);gen=FrameReader(raw);mr=FrameReader(mask,plan['start']);readers=[src,gen,mr]
            with av.open(str(temp),'w') as out:
                s=out.add_stream('libx264',rate=Fraction(meta['fps_ratio']));s.width=w*4;s.height=h;s.pix_fmt='yuv420p';s.time_base=Fraction(meta['time_base']);s.options={'qp':'0','preset':'ultrafast','bf':'0'}
                for second in meta['frame_times'][plan['start_frame']:plan['end_frame']]:
                    original=src.at(second,nearest=True,size=(w,h));generated=gen.at(second-plan['start'],nearest=True,size=(w,h))
                    mask_rgb=mr.at(second,nearest=True,size=(w,h));alpha=processed_mask(mask_rgb,{'grow':0,'feather':0})
                    support=alpha>1/255
                    if support.any():
                        inside=distance_transform_edt(np.pad(support,1))[1:-1,1:-1]
                        outside=distance_transform_edt(~support)
                        distance=(inside-outside)/(w/meta['width'])
                    else:distance=np.full((h,w),-field_range)
                    sdf=np.repeat(np.rint(np.clip(distance/field_range*.5+.5,0,1)*255).astype(np.uint8)[...,None],3,axis=2)
                    a=np.repeat(np.rint(alpha*255).astype(np.uint8)[...,None],3,axis=2)
                    atlas=np.concatenate((original,generated,sdf,a),axis=1)
                    frame=av.VideoFrame.from_ndarray(atlas,format='rgb24');frame.time_base=s.time_base;frame.pts=round((second-plan['start'])/frame.time_base)
                    for packet in s.encode(frame):out.mux(packet)
                for packet in s.encode():out.mux(packet)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
            for reader in readers:reader.close()
    base=composite_settings(mask_settings(e.get('mask')))
    return dict(file={'filename':path.name,'subfolder':'DOGMA_RESTITCH','type':'temp'},width=w,height=h,
                source_width=meta['width'],source_height=meta['height'],fps=meta['fps'],duration=plan['duration'],fade=e['fade'],
                field_range=field_range,base={'grow':base['grow'],'feather':base['feather']},revision=item.get('restitch_revision',0),
                elapsed_seconds=round(time.monotonic()-started,3),cache_key=key)

def validate_choice(data):
    grow,feather=(float(data.get(k,0)) for k in ('grow','feather'))
    if not all(math.isfinite(x) for x in (grow,feather)) or abs(grow)>256 or not 0<=feather<=256:
        raise ValueError('Restitch: espansione da −256 a +256 px e feather da 0 a 256 px.')
    return dict(composite_mode='source',composite_grow=round(grow),composite_feather=feather,composite_metric='distance')

def apply_restitch(core,data):
    from .dogma_h3_video_edit import cached_probe,plan_interval,compose
    choice=validate_choice(data)
    st,item,root,source,mask,raw,master,sha=inputs(core,data['session'],data['id'])
    if st.get('status')=='running':raise ValueError('Attendi la fine della generazione prima di applicare il restitch.')
    revision=int(item.get('restitch_revision',0))
    if int(data.get('revision',revision))!=revision:raise ValueError('Il finale è stato aggiornato. Riapri le varianti di restitch.')
    if sha and fingerprint(raw)!=sha:raise ValueError('Il tratto generato è stato modificato.')
    previous_hash=item.get('video_sha256') or fingerprint(master)
    if fingerprint(master)!=previous_hash:raise ValueError('Il master è stato modificato esternamente. Nessun file sovrascritto.')
    c=copy.deepcopy(item['config']);settings=mask_settings({**c['edit']['mask'],**choice});c['edit']['mask']=settings
    meta=cached_probe(source);validate_alignment(meta,cached_probe(mask));plan=plan_interval(meta,c['edit']['start'],c['edit']['end'])
    temp=master.with_name(master.stem+'.restitch-'+uuid.uuid4().hex+'.mp4')
    try:
        info=compose(source,raw,temp,meta,plan,c['edit']['fade'],mask_path=mask,settings=settings)
        new_hash=fingerprint(temp)
        with core._STATE_LOCK:
            latest=core.state(data['session']);current=next((x for x in latest.get('edits',[]) if x['id']==item['id']),None)
            if not current or latest.get('status')=='running' or current.get('restitch_revision',0)!=revision or fingerprint(master)!=previous_hash:
                raise ValueError('La sessione è cambiata durante il restitch. Il finale precedente è conservato.')
            temp.replace(master)
            saved=Path(current.get('saved_path',str(master)));error=None
            if saved.resolve()!=master.resolve():
                transfer=saved.with_name(saved.name+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    if not saved.is_file() or fingerprint(saved)!=previous_hash:raise ValueError('La copia esportata è stata spostata o modificata. Il nuovo master resta nella sessione.')
                    shutil.copy2(master,transfer);transfer.replace(saved)
                except (OSError,ValueError) as exc:error=str(exc);saved=master
                finally:transfer.unlink(missing_ok=True)
            current.setdefault('restitch_initial',{'grow':composite_settings(mask_settings(current['config']['edit']['mask']))['grow'],'feather':composite_settings(mask_settings(current['config']['edit']['mask']))['feather']})
            current.update(config=c,video_sha256=new_hash,saved_path=str(saved.resolve()),restitch_revision=revision+1,**info)
            current['video']={**current['video'],'dg_revision':revision+1}
            if error:current['export_error']=error
            else:current.pop('export_error',None)
            latest['message']='Restitch applicato al finale.' if not error else error
            core.write_json(root/'session.json',latest)
            return current
    finally:temp.unlink(missing_ok=True)

def register_routes(routes,core,authorize_request):
    from aiohttp import web
    jobs={};slot=asyncio.Semaphore(1)
    async def launch(kind,data):
        for k in list(jobs):
            if len(jobs)<24:break
            if jobs[k]['status'] in ('done','error'):jobs.pop(k)
        if len(jobs)>=24:raise web.HTTPTooManyRequests(text='Attendi le lavorazioni già avviate.')
        job={'id':uuid.uuid4().hex,'status':'running'};jobs[job['id']]=job
        async def run():
            try:
                async with slot:
                    result=await asyncio.to_thread(preview_atlas,core,data['session'],data['id'],960 if data.get('detail') is True else 320) if kind=='preview' else await asyncio.to_thread(apply_restitch,core,data)
                    job.update(status='done',result=result)
            except Exception as exc:job.update(status='error',message=str(exc))
        job['task']=asyncio.create_task(run());return web.json_response({'id':job['id']})
    @routes.post('/dogma/h3/v2/edit/restitch/preview')
    async def preview(request):authorize_request(request);return await launch('preview',await request.json())
    @routes.post('/dogma/h3/v2/edit/restitch/apply')
    async def apply(request):authorize_request(request);return await launch('apply',await request.json())
    @routes.get('/dogma/h3/v2/edit/restitch/job/{id}')
    async def status(request):
        authorize_request(request);job=jobs.get(request.match_info['id'])
        if not job:raise web.HTTPNotFound(text='Lavorazione non disponibile.')
        return web.json_response({k:v for k,v in job.items() if k!='task'})
    async def cleanup(app):await asyncio.gather(*(j['task'] for j in jobs.values()),return_exceptions=True)
    return cleanup
