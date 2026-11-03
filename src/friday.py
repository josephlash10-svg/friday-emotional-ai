"""Double-click start for RUN.bat: intro art, progress bars for the soul and the brain, then chat.

Friday speaks first. Heavy libraries are imported only after the art is on screen, so the
window never sits blank.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')
# The checkpoint stores its decoder path relative to the project folder.
os.chdir(ROOT)
os.environ.setdefault('HF_HUB_DISABLE_PROGRESS_BARS', '1')
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

from launcher_ui import banner, LoadingBar

def first_run_checkpoint():
    """A fresh copy (e.g. from GitHub) has no state/ folder: start from the clean base checkpoint.
    Never overwrites an existing checkpoint, which holds that user's memories."""
    live = ROOT / 'state/checkpoints/v14-language.pth'
    base = ROOT / 'release/friday-base.pth'
    if not live.exists() and base.exists():
        import shutil
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base, live)
        print('  First run: starting Friday with a fresh memory.\n', flush=True)

def main():
    first_run_checkpoint()
    banner()
    print()
    soul = LoadingBar('Soul', 'soul', 25).start()
    soul.reach(.05, 'waking up')
    import torch  # noqa: F401  (the slowest import; shown as its own milestone)
    soul.reach(.35, 'core libraries loaded')
    import warnings
    warnings.filterwarnings('ignore')
    from transformers.utils import logging as hf_logging
    hf_logging.set_verbosity_error()
    import model
    soul.reach(.5, 'restoring emotions and memories')
    sys.argv = [sys.argv[0], '--cpu-chat', '--speak-first', '--threads', '4'] + sys.argv[1:]
    model.main(ui={'soul': soul})

if __name__ == '__main__':
    main()
