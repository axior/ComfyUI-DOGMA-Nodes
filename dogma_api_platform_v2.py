"""Reference preparation, project output records and local workspace operations.

Generation remains in native partner API nodes, in independent async branches.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

_LOCK = threading.RLock()
_WORKSPACES = set()
_FRONTEND_CACHE = {}


def _output():
    import folder_paths
    return Path(folder_paths.get_output_directory()).resolve()


def _library():
    path = _output() / 'DOGMA' / 'API' / '.library'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean(value):
    return re.sub(r'[^\w.-]+', '_', str(value or '').strip(), flags=re.UNICODE).strip('.')[:100]


def _record(metadata, files, kind):
    data = json.loads(metadata)
    identifier = str(data.get('id', ''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier):
        raise ValueError('Identificatore output non valido.')
    data.update(kind=kind, images=files, status='completed', finished=int(time.time()*1000))
    root = _output()
    exported = []
    warning = ''
    workspace = Path(data['workspace']).expanduser().resolve() if data.get('workspace') else None
    # Only a directory selected through this browser session may be outside output.
    if workspace and not (workspace.is_relative_to(root) or str(workspace) in _WORKSPACES):
        warning = 'Copia nella cartella di lavoro non eseguita: riseleziona la cartella. Il file è salvato in Comfy output.'
        workspace = None
    if workspace:
        try:
            target = workspace
            for field in ('project', 'scene'):
                if _clean(data.get(field)):target /= _clean(data[field])
            target.mkdir(parents=True, exist_ok=True)
            for file in files:
                source = (root / file.get('subfolder', '') / file['filename']).resolve()
                if not source.is_relative_to(root):raise ValueError('Output non valido.')
                destination = target / source.name
                if destination != source:
                    # Job IDs prevent a different project/run from replacing a file.
                    if destination.exists():destination = target / (source.stem+'_'+identifier[:8]+source.suffix)
                    shutil.copy2(source, destination)
                exported.append(str(destination))
            sidecar = target / (identifier+'.dogma.json')
            sidecar.write_text(json.dumps({**data, 'exported': exported, 'dogma_schema':3, 'workspace_relative':target.relative_to(workspace).as_posix()}, ensure_ascii=False, indent=2), encoding='utf8')
        except (OSError, ValueError) as exc:
            warning = 'File salvato in Comfy; copia nella cartella di lavoro non riuscita: '+str(exc)
    if not workspace:
        for file in files:
            target=root/file.get('subfolder','')
            (target/(identifier+'.dogma.json')).write_text(json.dumps({**data,'dogma_schema':3},ensure_ascii=False,indent=2),encoding='utf8')
    data['exported'] = exported
    if warning:data['warning'] = warning
    path = _library() / (identifier+'.json')
    temporary = path.with_suffix('.tmp')
    with _LOCK:
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        temporary.replace(path)
    return data


def _import_workspace(root):
    """Portable sidecars travel with the output; no inference from filename tags."""
    root=Path(root).resolve();records=[];seen=set()
    from itertools import chain
    legacy=(p for directory in root.rglob('.library') if directory.is_dir() for p in directory.glob('*.json'))
    for path in chain(root.rglob('*.dogma.json'),legacy):
        if len(records)>=5000:break
        if not path.resolve().is_relative_to(root):continue
        try:
            data=json.loads(path.read_text('utf8'));identifier=str(data.get('id',''))
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identifier):continue
            if identifier in seen:continue
            files=[];exported=[]
            for index,original in enumerate(data.get('images',[])):
                copies=data.get('exported',[])
                name=Path(copies[index].replace('\\','/')).name if index<len(copies) else Path(original.get('filename','')).name
                if path.parent.name=='.library':
                    subfolder=str(original.get('subfolder','')).replace('\\','/')
                    relative=subfolder.removeprefix('DOGMA/API').lstrip('/')
                    candidate=(path.parent.parent/relative/name).resolve()
                else:candidate=(path.parent/name).resolve()
                if not candidate.is_relative_to(root) or not candidate.is_file():continue
                files.append({'filename':name,'workspace':str(root),'relative':candidate.relative_to(root).as_posix(),'type':'workspace',**({'variant':original['variant']} if original.get('variant') else {})})
                exported.append(str(candidate))
            if not files:continue
            data.update(workspace=str(root),images=files,exported=exported,status='completed',imported=True)
            (_library()/(identifier+'.json')).write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
            records.append(data);seen.add(identifier)
        except (ValueError,OSError,KeyError,TypeError):continue
    return records


_SAM_LOCK = threading.Lock()


def prompt_mask(source, image, settings):
    """Compute the installed SAM3 node once and retain the exact mask for Run."""
    import inspect
    import numpy as np
    import torch
    import nodes
    import folder_paths
    from PIL import Image
    prompt = str(settings.get('prompt', '')).strip()
    if not prompt:raise ValueError('Scrivi cosa selezionare in MASK PROMPT.')
    node_class = nodes.NODE_CLASS_MAPPINGS.get('SAM3Segment')
    if node_class is None:raise ValueError('SAM3 non è disponibile. Installa o abilita il nodo SAM3Segment di ComfyUI-RMBG e riavvia Comfy.')
    stat = source.stat()
    signature = json.dumps([str(source),stat.st_mtime_ns,stat.st_size,prompt,int(settings.get('segment') or 0),node_class.__module__],ensure_ascii=False)
    digest = hashlib.sha256(signature.encode()).hexdigest()
    directory = Path(folder_paths.get_input_directory())/'DOGMA_API'/'masks'
    directory.mkdir(parents=True,exist_ok=True)
    path = directory/('sam3_'+digest+'.png')
    with _SAM_LOCK:
        if not path.is_file():
            instance = node_class()
            function = getattr(instance,node_class.FUNCTION)
            specs = node_class.INPUT_TYPES()
            values = {}
            for name,spec in {**specs.get('required',{}),**specs.get('optional',{})}.items():
                options=spec[1] if len(spec)>1 and isinstance(spec[1],dict) else {}
                if 'default' in options:values[name]=options['default']
                elif isinstance(spec[0],list) and spec[0]:values[name]=spec[0][0]
            values.update(image=torch.from_numpy(np.asarray(image.convert('RGB')).copy()).float().unsqueeze(0)/255,prompt=prompt,output_mode='Merged',confidence_threshold=.5,max_segments=0,segment_pick=int(settings.get('segment') or 0),mask_blur=0,mask_offset=0,device='Auto',invert_output=False,unload_model=True,background='Alpha',background_color='#222222')
            parameters=inspect.signature(function).parameters
            values={key:value for key,value in values.items() if key in parameters}
            with torch.inference_mode():result=function(**values)
            if isinstance(result,dict):result=result.get('result',())
            if not result or len(result)<2:raise ValueError('SAM3 non ha restituito una maschera.')
            masks=result[1].detach().cpu()
            if masks.numel()==0:mask=Image.new('L',image.size,0)
            else:
                if masks.ndim==3:masks=masks.amax(dim=0)
                mask=Image.fromarray((masks.numpy().clip(0,1)*255).astype(np.uint8)).resize(image.size,Image.Resampling.NEAREST)
            temporary=path.with_suffix('.tmp')
            mask.save(temporary,format='PNG');temporary.replace(path)
    return Image.open(path).convert('L'), 'DOGMA_API/masks/'+path.name


def process_reference(image, mask, settings):
    """Shared Pillow operation used by the node and by the no-generation preview."""
    import numpy as np
    from PIL import Image, ImageOps, ImageFilter, ImageColor
    from scipy import ndimage
    cfg = json.loads(settings) if isinstance(settings, str) else settings
    image = image.convert('RGB')
    mask = mask.convert('L').resize(image.size, Image.Resampling.NEAREST)
    if cfg.get('flip'):
        image = ImageOps.mirror(image);mask = ImageOps.mirror(mask)
    if cfg.get('resizeMpx'):
        megapixels = max(.01, min(64, float(cfg.get('megapixels', 1))))
        scale = (megapixels*1e6/(image.width*image.height))**.5
        size = (max(1, round(image.width*scale)), max(1, round(image.height*scale)))
        image = image.resize(size, Image.Resampling.LANCZOS);mask = mask.resize(size, Image.Resampling.NEAREST)
    if cfg.get('invert'):mask = ImageOps.invert(mask)
    if cfg.get('fillHoles'):
        arr = np.asarray(mask);filled = ndimage.binary_fill_holes(arr>127)
        mask = Image.fromarray(np.maximum(arr, filled.astype(np.uint8)*255))
    grow = max(-512, min(512, int(cfg.get('expand', 0))))
    if grow:
        array = np.asarray(mask)
        fun = ndimage.maximum_filter if grow>0 else ndimage.minimum_filter
        mask = Image.fromarray(fun(array, size=abs(grow)*2+1))
    blur = max(0, min(128, float(cfg.get('blur', 0))))
    if blur:mask = mask.filter(ImageFilter.GaussianBlur(blur))
    crop_box = None
    if cfg.get('crop'):
        rect = cfg.get('cropRect')
        if rect:
            x,y,w,h = [max(0,min(1,float(n))) for n in rect]
            if cfg.get('flip'):x=max(0,1-x-w)
            crop_box = (round(x*image.width),round(y*image.height),round(min(1,x+w)*image.width),round(min(1,y+h)*image.height))
        else:crop_box = mask.point(lambda v:255 if v>25 else 0).getbbox()
        if not crop_box or crop_box[2]<=crop_box[0] or crop_box[3]<=crop_box[1]:
            raise ValueError('Crop vuoto: seleziona un’area o dipingi una maschera.')
    if cfg.get('mask'):
        background = Image.new('RGB', image.size, ImageColor.getrgb(cfg.get('background') or '#ff00ff'))
        image = Image.composite(background,image,mask) if cfg.get('maskMode')=='edit' else Image.composite(image,background,mask)
    if crop_box:image=image.crop(crop_box);mask=mask.crop(crop_box)
    width,height = int(cfg.get('targetWidth') or 0),int(cfg.get('targetHeight') or 0)
    if cfg.get('crop') and width>0 and height>0:
        if width>16384 or height>16384:raise ValueError('Dimensioni crop troppo grandi.')
        image=image.resize((width,height),Image.Resampling.LANCZOS);mask=mask.resize((width,height),Image.Resampling.NEAREST)
    return image,mask


class DOGMAAPIReferenceV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image':('IMAGE',), 'mask':('MASK',), 'settings':('STRING',{'default':'{}'})}}
    RETURN_TYPES=('IMAGE',)
    FUNCTION='prepare'
    CATEGORY='DOGMA/API Platform'

    def prepare(self,image,mask,settings):
        import numpy as np
        import torch
        from PIL import Image
        results=[]
        for index in range(image.shape[0]):
            pil=Image.fromarray((image[index].detach().cpu().numpy().clip(0,1)*255).astype(np.uint8))
            alpha=Image.fromarray((mask[min(index,len(mask)-1)].detach().cpu().numpy().clip(0,1)*255).astype(np.uint8))
            processed,_=process_reference(pil,alpha,settings)
            results.append(torch.from_numpy(np.asarray(processed).copy()).float()/255)
        return (torch.stack(results),)


def _save_prefix(data):
    basename=Path(str(data.get('prefix') or 'DOGMA').replace('\\','/')).name
    return '/'.join(['DOGMA','API',*[_clean(data.get(k)) for k in ('project','scene') if _clean(data.get(k))],basename])


class DOGMAAPIImageOutputV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'metadata':('STRING',)},'hidden':{'prompt':'PROMPT','extra_pnginfo':'EXTRA_PNGINFO'}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='save'
    CATEGORY='DOGMA/API Platform'

    def save(self,images,metadata,prompt=None,extra_pnginfo=None):
        from nodes import SaveImage
        data=json.loads(metadata)
        # Same output and metadata behavior as the native SaveImage node.
        result=SaveImage().save_images(images,_save_prefix(data),prompt,extra_pnginfo)
        record=_record(metadata,result['ui']['images'],'image')
        return {'ui':{**result['ui'],'dogma_records':[record]},'result':()}


class DOGMAAPIVideoOutputV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'video':('VIDEO',),'metadata':('STRING',)},'hidden':{'prompt':'PROMPT','extra_pnginfo':'EXTRA_PNGINFO'}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='save'
    CATEGORY='DOGMA/API Platform'

    async def save(self,video,metadata,prompt=None,extra_pnginfo=None):
        cancelled=threading.Event()
        worker=asyncio.create_task(asyncio.to_thread(self._save,video,metadata,prompt,extra_pnginfo,cancelled))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled.set()
            # Let the worker retain the generated original and remove its partial fix.
            try:await worker
            except Exception:pass
            raise

    def _save(self,video,metadata,prompt=None,extra_pnginfo=None,cancelled=None):
        from comfy_api.latest import Types
        import folder_paths
        from comfy.cli_args import args
        data=json.loads(metadata);width,height=video.get_dimensions()
        with _LOCK:
            folder,stem,counter,subfolder,_=folder_paths.get_save_image_path(_save_prefix(data),str(_output()),width,height)
            while True:
                filename=f'{stem}_{counter:05}_.mp4';source=Path(folder)/filename
                try:
                    # Reserve before releasing the lock; async branches must never overwrite.
                    with source.open('xb'):pass
                    break
                except FileExistsError:counter+=1
        saved_metadata=None if args.disable_metadata else {**(extra_pnginfo or {}),'prompt':prompt}
        try:
            video.save_to(str(source),format=Types.VideoContainer('mp4'),codec=Types.VideoCodec('auto'),metadata=saved_metadata)
        except BaseException:
            source.unlink(missing_ok=True)
            raise
        files=[{'filename':filename,'subfolder':subfolder,'type':'output','format':'video/mp4'}]
        if data.get('videoRepair'):
            files[0]['variant']='original'
            try:
                from .dogma_video_repair import repair_video
                import comfy.model_management as management
                from server import PromptServer
                def progress(stage, fraction):
                    # The job ID is stable before/after the batch receives its prompt ID.
                    PromptServer.instance.send_sync('dogma_video_repair',{'job_id':data['id'],'stage':stage,'value':fraction})
                def check_cancel():
                    from .dogma_video_repair import RepairCancelled
                    if cancelled is not None and cancelled.is_set():raise RepairCancelled('Correzione interrotta.')
                    management.throw_exception_if_processing_interrupted()
                fixed=source.with_name(source.stem+'_FIX.mp4')
                report=repair_video(source,fixed,Path(folder_paths.models_dir)/'DOGMA'/'rife',
                                    cancel=check_cancel,progress=progress)
                data['repair']=report
                files.append({'filename':fixed.name,'subfolder':subfolder,'type':'output','format':'video/mp4',
                              'variant':'repaired' if report['status']=='repaired' else 'checked'})
                if report['status']=='skipped_quality':
                    data['warning']='Fix non applicato: il controllo del movimento non ha confermato un miglioramento. La seconda copia conserva l’originale.'
            except Exception as exc:
                # Never repeat a paid generation when only local post-processing fails.
                data['repair']={'status':'failed','error':str(exc)}
                data['warning']='Originale salvato. Correzione scatti non completata: '+(str(exc) or 'interrotta')
        record=_record(json.dumps(data,ensure_ascii=False),files,'video')
        return {'ui':{'images':files,'animated':(True,),'dogma_records':[record]},'result':()}


def frontend_modules(web_root):
    """Discover the installed frontend's own shared billing/pricing modules."""
    cache_key=str(web_root)
    if cache_key in _FRONTEND_CACHE:return _FRONTEND_CACHE[cache_key]
    assets=Path(web_root)/'assets';result={}
    for path in assets.glob('*.js'):
        if path.name.startswith('useBillingContext-'):
            text=path.read_text('utf8');exports=text[text.rfind('export{'):]
            match=re.search(r'useNodePricing as (\w+)',exports)
            shared=re.search(r'(\w+)=\w+\(useBillingContextInternal\)',text)
            alias=re.search(r'\b'+re.escape(shared[1])+r' as (\w+)',exports) if shared else None
            if match and alias:result['billing']={'file':path.name,'context':alias[1],'pricing':match[1]}
        elif path.name.startswith('creditsUtil-'):
            text=path.read_text('utf8');match=re.search(r'formatCreditsFromCents as (\w+)',text)
            if match:result['credits']={'file':path.name,'format':match[1]}
    _FRONTEND_CACHE[cache_key]=result
    return result


def register_routes():
    from aiohttp import web
    from server import PromptServer
    from .dogma_h3_access import H3Access
    import folder_paths
    access=H3Access();routes=PromptServer.instance.routes

    @routes.get('/dogma/api/v2/catalog')
    async def catalog(request):
        capabilities=access.catalog(request,_output())
        return web.json_response({'access':{**capabilities,'output_root':str(_output()/'DOGMA'/'API')},'frontend':frontend_modules(PromptServer.instance.web_root),'version':'1.0.56'})

    @routes.post('/dogma/api/v2/workspace')
    async def workspace(request):
        access.browser(request);data=await request.json()
        try:
            path=access.output_path(request,data.get('path'),_output())
            if not path.is_dir():raise ValueError('Scegli una cartella esistente.')
            _WORKSPACES.add(str(path))
            records=await asyncio.to_thread(_import_workspace,path)
            return web.json_response({'path':str(path),'records':records})
        except (ValueError,OSError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.post('/dogma/api/v2/choose-folder')
    async def choose(request):
        access.browser(request)
        return web.json_response({'browse':True})

    @routes.get('/dogma/api/v2/folders')
    async def folders(request):
        access.browser(request)
        try:
            path=access.output_path(request,request.query.get('path') or str(_library().parent),_output())
            if not path.is_dir():raise ValueError('Cartella inesistente.')
            local=access.is_local(request)
            def scan():
                dirs=[];files=[]
                for p in path.iterdir():
                    if p.name.startswith('.'):continue
                    try:
                        if not local and not p.resolve().is_relative_to(_output()):continue
                        if p.is_dir():dirs.append({'name':p.name,'path':str(p.resolve())})
                        elif p.is_file():files.append({'name':p.name})
                    except OSError:continue
                parent=str(path.parent) if path.parent!=path and (local or path.parent.is_relative_to(_output())) else None
                roots=[]
                if local and os.name=='nt':
                    roots=[{'name':letter+':','path':letter+':/'} for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if Path(letter+':/').is_dir()]
                return {'path':str(path),'parent':parent,'roots':roots,'directories':sorted(dirs,key=lambda d:d['name'].lower()),'files':sorted(files,key=lambda d:d['name'].lower())[:5000]}
            return web.json_response(await asyncio.to_thread(scan))
        except (ValueError,OSError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.post('/dogma/api/v2/mkdir')
    async def mkdir(request):
        access.browser(request);data=await request.json()
        try:
            parent=access.output_path(request,data.get('path'),_output())
            name=str(data.get('name','')).strip()
            if not name or name in ('.','..') or re.search(r'[<>:"/\\|?*]',name) or name.endswith(('.', ' ')):raise ValueError('Nome cartella non valido.')
            target=parent/name
            if not parent.is_dir():raise ValueError('Cartella superiore inesistente.')
            target.mkdir(exist_ok=False)
            return web.json_response({'path':str(target.resolve())})
        except (ValueError,OSError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.get('/dogma/api/v2/workspace-media')
    async def workspace_media(request):
        access.fetch_site(request)
        try:
            root=access.output_path(request,request.query.get('workspace'),_output())
            if str(root) not in _WORKSPACES:raise ValueError('Riseleziona la cartella di lavoro.')
            relative=request.query.get('relative','');file=(root/relative).resolve()
            if not file.is_relative_to(root) or file.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.mp4','.webm','.mov'):raise ValueError('File non valido.')
            if not file.is_file():raise ValueError('File non disponibile.')
            return web.FileResponse(file)
        except (ValueError,OSError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.get('/dogma/api/v2/library')
    async def library(request):
        access.browser(request)
        def read():
            records=[]
            for path in sorted(_library().glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:5000]:
                try:records.append(json.loads(path.read_text('utf8')))
                except (ValueError,OSError):continue
            return records
        return web.json_response({'records':await asyncio.to_thread(read)})

    @routes.post('/dogma/api/v2/open-output')
    async def open_output(request):
        access.browser(request)
        data=await request.json();identifier=str(data.get('id',''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identifier):raise web.HTTPBadRequest(text='Output non valido.')
        try:
            record=json.loads((_library()/(identifier+'.json')).read_text('utf8'))
            index=max(0,int(data.get('index',0)));copies=record.get('exported',[])
            file=Path(copies[index]) if index<len(copies) else _output()/record['images'][index].get('subfolder','')/record['images'][index]['filename']
            if not file.is_file():raise ValueError('Il file è stato spostato o rimosso.')
            access.output_path(request,str(file.parent),_output())
            return web.json_response({'path':str(file.parent),'filename':file.name})
        except (ValueError,OSError,IndexError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.post('/dogma/api/v2/explorer')
    async def explorer(request):
        access.browser(request)
        if not access.is_local(request) or os.name!='nt':
            raise web.HTTPBadRequest(text='Esplora file è disponibile sul computer Windows che esegue Comfy. Usa il browser cartelle su un server remoto.')
        data=await request.json()
        try:
            path=access.output_path(request,data.get('path'),_output())
            if not path.is_dir():raise ValueError('Cartella inesistente.')
            os.startfile(str(path))
            return web.json_response({'opened':True})
        except (ValueError,OSError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.post('/dogma/api/v2/reference-preview')
    async def preview(request):
        access.browser(request);data=await request.json()
        from PIL import Image,ImageOps
        def prepare():
            source=Path(folder_paths.get_annotated_filepath(data['file'])).resolve()
            if not source.is_relative_to(Path(folder_paths.get_input_directory()).resolve()):raise ValueError('Reference esterna a input.')
            rgba=ImageOps.exif_transpose(Image.open(source)).convert('RGBA');mask=ImageOps.invert(rgba.getchannel('A'))
            settings=data['settings']
            sam_file=None
            if settings.get('source')=='prompt' and settings.get('mask'):
                mask,sam_file=prompt_mask(source,rgba,settings)
            elif settings.get('maskFile'):
                mask_path=Path(folder_paths.get_annotated_filepath(settings['maskFile'])).resolve()
                if not mask_path.is_relative_to(Path(folder_paths.get_input_directory()).resolve()):raise ValueError('Maschera esterna a input.')
                mask=Image.open(mask_path).convert('L')
            result,_=process_reference(rgba,mask,settings)
            directory=Path(folder_paths.get_input_directory())/'DOGMA_API'/'previews';directory.mkdir(parents=True,exist_ok=True)
            filename='ref_'+uuid.uuid4().hex+'.png';result.save(directory/filename)
            response={'file':'DOGMA_API/previews/'+filename,'width':result.width,'height':result.height}
            if sam_file:response.update(maskFile=sam_file,samSource=data['file'],samPrompt=settings['prompt'],samSegment=int(settings.get('segment') or 0),emptyMask=not bool(mask.getbbox()))
            return response
        try:return web.json_response(await asyncio.to_thread(prepare))
        except (ValueError,OSError,KeyError,RuntimeError,ImportError) as exc:raise web.HTTPBadRequest(text=str(exc))


NODE_CLASS_MAPPINGS={'DOGMAAPIReferenceV2':DOGMAAPIReferenceV2,'DOGMAAPIImageOutputV2':DOGMAAPIImageOutputV2,'DOGMAAPIVideoOutputV2':DOGMAAPIVideoOutputV2}
NODE_DISPLAY_NAME_MAPPINGS={'DOGMAAPIReferenceV2':'DOGMA / Reference preparation','DOGMAAPIImageOutputV2':'DOGMA / Image output','DOGMAAPIVideoOutputV2':'DOGMA / Video output'}
