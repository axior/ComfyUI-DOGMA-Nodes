"""Run CPU-only regression tests without importing ComfyUI's package entry point."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='dogma-tests-') as td:
    test=Path(td)/'test_v566.py'
    shutil.copyfile(root/'tests/test_v566.py',test)
    env=dict(os.environ,DOGMA_V566_MODULE=str(root/'dogma_semantic_v566.py'))
    sys.exit(subprocess.call([sys.executable,'-m','pytest',str(test),'-q','--tb=short'],env=env,cwd=td))
