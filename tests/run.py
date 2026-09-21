"""Run CPU-only regression tests without importing ComfyUI's package entry point."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dogma-tests-') as td:
    for name in ('test_v566.py','test_v567.py'):
        shutil.copyfile(root/'tests'/name,Path(td)/name)
    env=dict(os.environ,DOGMA_V566_MODULE=str(root/'dogma_semantic_v566.py'),DOGMA_V567_MODULE=str(root/'dogma_semantic_v567.py'))
    sys.exit(subprocess.call([sys.executable,'-m','pytest',td,'-q','--tb=short','-p','no:cacheprovider'],env=env,cwd=td))
