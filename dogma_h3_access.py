"""Browser request proof for H3 data operations; OS actions remain local-only.

The token complements the deployment's existing Comfy/proxy authentication.
It is not a replacement for authentication on a publicly exposed Comfy server.
Forwarded headers never grant access or widen the filesystem scope.
"""
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web

class H3Access:
    def __init__(self):self.token=secrets.token_urlsafe(32)

    @staticmethod
    def fetch_site(request):
        site=request.headers.get('Sec-Fetch-Site','').lower()
        if site and site not in ('same-origin','none'):
            raise web.HTTPForbidden(text='Richiesta da un altro sito non consentita.')
        origin=request.headers.get('Origin')
        if origin:
            try:valid=origin!='null' and urlsplit(origin).scheme in ('http','https') and bool(urlsplit(origin).netloc)
            except ValueError:valid=False
            if not valid:raise web.HTTPForbidden(text='Origine non valida.')

    def is_local(self,request):
        if request.remote not in ('127.0.0.1','::1'):return False
        try:
            host=urlsplit('//'+request.host)
            if host.hostname not in ('127.0.0.1','::1','localhost'):return False
            origin=request.headers.get('Origin')
            if origin and urlsplit(origin).netloc.lower()!=host.netloc.lower():return False
            self.fetch_site(request)
        except (ValueError,web.HTTPForbidden):return False
        return True

    def local(self,request):
        if not self.is_local(request):
            raise web.HTTPForbidden(text='Questa azione del sistema è disponibile solo da localhost sul computer Comfy.')

    def browser(self,request):
        self.fetch_site(request)
        token=request.headers.get('X-Dogma-Access','')
        if not token or not secrets.compare_digest(token.encode('utf8'),self.token.encode('ascii')):
            raise web.HTTPForbidden(text='Accesso DOGMA scaduto o pannello precedente. Ricarica la pagina e riapri H3 Director.')
        if request.method=='POST' and request.content_type!='application/json':
            raise web.HTTPUnsupportedMediaType(text='Richiesta JSON necessaria.')

    def catalog(self,request,output):
        self.fetch_site(request)
        import os
        return {'token':self.token,'local_files':self.is_local(request),
                'open_folder':self.is_local(request) and os.name=='nt',
                'output_directory':str(Path(output).resolve()),'platform':os.name}

    def output_path(self,request,path,root):
        root=Path(root).expanduser().resolve()
        destination=Path(path).expanduser().resolve() if path else root
        if not self.is_local(request) and not destination.is_relative_to(root):
            raise ValueError('Da remoto scegli una cartella dentro l’output di Comfy: '+str(root))
        return destination
