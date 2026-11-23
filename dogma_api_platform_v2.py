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
            sidecar.write_text(json.dumps({**data, 'exported': exported}, ensure_ascii=False, indent=2), encoding='utf8')
        except (OSError, ValueError) as exc:
            warning = 'File salvato in Comfy; copia nella cartella di lavoro non riuscita: '+str(exc)
    data['exported'] = exported
    if warning:data['warning'] = warning
    path = _library() / (identifier+'.json')
    temporary = path.with_suffix('.tmp')
    with _LOCK:
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        temporary.replace(path)
    return data


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
        background = Image.new('RGB', image.size, ImageColor.getrgb(cfg.get('background') or '#00ff00'))
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
        result=SaveImage().save_images(images,data['prefix'],prompt,extra_pnginfo)
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

    def save(self,video,metadata,prompt=None,extra_pnginfo=None):
        from comfy_api.latest import Types
        import folder_paths
        from comfy.cli_args import args
        data=json.loads(metadata);width,height=video.get_dimensions()
        folder,filename,counter,subfolder,_=folder_paths.get_save_image_path(data['prefix'],str(_output()),width,height)
        filename=f'{filename}_{counter:05}_.mp4'
        saved_metadata=None if args.disable_metadata else {**(extra_pnginfo or {}),'prompt':prompt}
        video.save_to(str(Path(folder)/filename),format=Types.VideoContainer('mp4'),codec=Types.VideoCodec('auto'),metadata=saved_metadata)
        files=[{'filename':filename,'subfolder':subfolder,'type':'output','format':'video/mp4'}]
        record=_record(metadata,files,'video')
        return {'ui':{'images':files,'animated':(True,),'dogma_records':[record]},'result':()}


def frontend_modules(web_root):
    """Discover the installed frontend's own shared billing/pricing modules."""
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
        return web.json_response({'access':capabilities,'frontend':frontend_modules(PromptServer.instance.web_root),'version':'1.0.54'})

    @routes.post('/dogma/api/v2/workspace')
    async def workspace(request):
        access.browser(request);data=await request.json()
        try:
            path=access.output_path(request,data.get('path'),_output())
            if not path.is_dir():raise ValueError('Scegli una cartella esistente.')
            _WORKSPACES.add(str(path))
            return web.json_response({'path':str(path)})
        except (ValueError,OSError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.post('/dogma/api/v2/choose-folder')
    async def choose(request):
        access.browser(request);access.local(request)
        if os.name!='nt':raise web.HTTPBadRequest(text='Usa il browser delle cartelle sul server.')
        data=await request.json();initial=str(data.get('path') or _output())
        script="""[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'DOGMA / Scegli la cartella di lavoro'
$dialog.SelectedPath = $env:DOGMA_FOLDER_INITIAL
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Write($dialog.SelectedPath) }
"""
        def select():
            env=os.environ.copy();env['DOGMA_FOLDER_INITIAL']=initial
            result=subprocess.run(['powershell.exe','-NoProfile','-STA','-WindowStyle','Hidden','-Command',script],capture_output=True,env=env,encoding='utf8',timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError('La scelta cartella non è riuscita.')
            return result.stdout.strip()
        try:
            selected=await asyncio.to_thread(select)
            if selected:_WORKSPACES.add(str(Path(selected).resolve()))
            return web.json_response({'path':selected,'cancelled':not selected})
        except (ValueError,OSError,subprocess.TimeoutExpired) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.get('/dogma/api/v2/folders')
    async def folders(request):
        access.browser(request)
        try:
            path=access.output_path(request,request.query.get('path'),_output())
            if not path.is_dir():raise ValueError('Cartella inesistente.')
            dirs=[{'name':p.name,'path':str(p.resolve())} for p in path.iterdir() if p.is_dir() and (access.is_local(request) or p.resolve().is_relative_to(_output()))]
            parent=str(path.parent) if access.is_local(request) or path.parent.is_relative_to(_output()) else None
            return web.json_response({'path':str(path),'parent':parent,'directories':sorted(dirs,key=lambda d:d['name'].lower())})
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
        access.browser(request);access.local(request)
        data=await request.json();identifier=str(data.get('id',''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identifier):raise web.HTTPBadRequest(text='Output non valido.')
        try:
            record=json.loads((_library()/(identifier+'.json')).read_text('utf8'))
            index=max(0,int(data.get('index',0)));copies=record.get('exported',[])
            file=Path(copies[index]) if index<len(copies) else _output()/record['images'][index].get('subfolder','')/record['images'][index]['filename']
            if not file.is_file():raise ValueError('Il file è stato spostato o rimosso.')
            if os.name=='nt':subprocess.Popen(['explorer.exe','/select,',str(file)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:raise ValueError('Esplora risorse è disponibile sul Comfy Windows locale.')
            return web.json_response({'ok':True})
        except (ValueError,OSError,IndexError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))

    @routes.post('/dogma/api/v2/reference-preview')
    async def preview(request):
        access.browser(request);data=await request.json()
        from PIL import Image,ImageOps
        def prepare():
            source=Path(folder_paths.get_annotated_filepath(data['file'])).resolve()
            if not source.is_relative_to(Path(folder_paths.get_input_directory()).resolve()):raise ValueError('Reference esterna a input.')
            rgba=Image.open(source).convert('RGBA');mask=ImageOps.invert(rgba.getchannel('A'))
            settings=data['settings']
            if settings.get('source')=='prompt' and settings.get('mask'):raise ValueError('La maschera da testo viene calcolata da SAM3 durante Run. Per l’anteprima usa una maschera dipinta.')
            if settings.get('maskFile'):
                mask_path=Path(folder_paths.get_annotated_filepath(settings['maskFile'])).resolve()
                if not mask_path.is_relative_to(Path(folder_paths.get_input_directory()).resolve()):raise ValueError('Maschera esterna a input.')
                mask=Image.open(mask_path).convert('L')
            result,_=process_reference(rgba,mask,settings)
            directory=Path(folder_paths.get_input_directory())/'DOGMA_API'/'previews';directory.mkdir(parents=True,exist_ok=True)
            filename='ref_'+uuid.uuid4().hex+'.png';result.save(directory/filename)
            return {'file':'DOGMA_API/previews/'+filename,'width':result.width,'height':result.height}
        try:return web.json_response(await asyncio.to_thread(prepare))
        except (ValueError,OSError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))


NODE_CLASS_MAPPINGS={'DOGMAAPIReferenceV2':DOGMAAPIReferenceV2,'DOGMAAPIImageOutputV2':DOGMAAPIImageOutputV2,'DOGMAAPIVideoOutputV2':DOGMAAPIVideoOutputV2}
NODE_DISPLAY_NAME_MAPPINGS={'DOGMAAPIReferenceV2':'DOGMA / Reference preparation','DOGMAAPIImageOutputV2':'DOGMA / Image output','DOGMAAPIVideoOutputV2':'DOGMA / Video output'}
