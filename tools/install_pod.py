"""Install the reviewed DOGMA v1.0.5 release, keeping the old pack as backup."""
import ast
import datetime
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def locate():
    def valid(p):return all((p/q).exists() for q in ('main.py','comfy','custom_nodes'))
    override=os.environ.get('COMFY_ROOT')
    if override:
        p=Path(override).resolve()
        if not valid(p):raise RuntimeError('COMFY_ROOT non valido.')
        return p
    active=set()
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            for arg in (proc/'cmdline').read_bytes().decode().split('\0'):
                if arg and Path(arg).name=='main.py':
                    script=Path(arg)
                    if not script.is_absolute():script=(proc/'cwd').resolve()/script
                    p=script.parent.resolve()
                    if valid(p):active.add(p)
        except (OSError,UnicodeError):pass
    common=[Path.cwd(),*Path.cwd().parents,*map(Path,('/workspace/ComfyUI','/workspace/comfyui','/opt/ComfyUI','/app/ComfyUI','/root/ComfyUI'))]
    found=active or {p.resolve() for p in common if valid(p)}
    if len(found)!=1:raise RuntimeError('Imposta COMFY_ROOT=/percorso/ComfyUI. Cartelle trovate: '+str(sorted(map(str,found))))
    return found.pop()


def main():
    root=locate();print('ComfyUI:',root,flush=True)
    tag='v1.0.5'
    with tempfile.TemporaryDirectory(prefix='.dogma-install-',dir=root) as td:
        stage=Path(td)/'repo'
        subprocess.run(['git','clone','--depth','1','--branch',tag,'https://github.com/axior/ComfyUI-DOGMA-Nodes.git',str(stage)],check=True)
        version=re.search(r'^version\s*=\s*"([^"]+)"',(stage/'pyproject.toml').read_text(),re.M).group(1)
        if version!='1.0.5':raise RuntimeError('Versione inattesa: '+version)
        for p in stage.glob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
        if not (stage/'dogma_semantic_v566.py').is_file():raise RuntimeError('Manca il modulo corretto della fase 3.')
        python=next((str(p) for p in [root/'.venv/bin/python',root/'venv/bin/python'] if p.is_file()),sys.executable)
        subprocess.run([python,'-m','pip','install','-r',str(stage/'requirements.txt')],check=True)
        backup=root/'.dogma_backups'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup.mkdir(parents=True)
        custom=root/'custom_nodes';moved=[];target=custom/'comfyui-dogma-nodes'
        try:
            for old in custom.iterdir():
                if old.name.lower().replace('-','').replace('_','')=='comfyuidogmanodes':
                    dest=backup/old.name;old.rename(dest);moved.append((old,dest))
            stage.rename(target)
        except Exception:
            for old,dest in reversed(moved):
                if not old.exists():dest.rename(old)
            raise
        print('DOGMA 1.0.5 installato. Backup:',backup)
    print('Riavvia ComfyUI dal pannello. Poi Ctrl+F5 e carica DOGMA_COMPLEX_V56_17_MASKS_CAPTIONS_LINUX.json.')


if __name__=='__main__':
    main()
