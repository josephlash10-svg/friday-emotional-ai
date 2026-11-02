"""Fetch the third-party files Friday needs (not stored in the repository).

  python scripts/download_models.py

Downloads, then verifies by SHA-256 where the exact file is known:
  * Qwen3.5-4B (Q4_K_M GGUF, unsloth conversion)   Apache-2.0  -> data/models/qwen3.5-4b-gguf/
  * SmolLM2-135M-Instruct (pinned revision)        Apache-2.0  -> data/models/smollm2-135m-instruct/
  * all-MiniLM-L6-v2 (pinned revision, ~91 MB)     Apache-2.0  -> data/models/all-minilm-l6-v2/  (recall by meaning)
  * llama.cpp b11429 CPU build for Windows, Linux or macOS (x64 or ARM64)   MIT   -> runtime/llama-<arch>/
Files already present and matching are skipped. See THIRD_PARTY_NOTICES.md for licenses.
"""
import hashlib
import io
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QWEN = dict(repo='unsloth/Qwen3.5-4B-GGUF', file='Qwen3.5-4B-Q4_K_M.gguf',
            sha256='00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4', folder='data/models/qwen3.5-4b-gguf')
SMOL = dict(repo='HuggingFaceTB/SmolLM2-135M-Instruct', revision='12fd25f77366fa6b3b4b768ec3050bf629380bac',
            weights_sha256='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c', folder='data/models/smollm2-135m-instruct')
MINILM = dict(repo='sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41',
              weights_sha256='53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db', folder='data/models/all-minilm-l6-v2')
LLAMA_TAG = 'b11429'  # commit d81235049384534c167caea52b85a694f6103d14, the build Friday was tested with
# The prebuilt CPU servers in that release, with the SHA-256 GitHub publishes for each file. They hold the
# programs Friday runs, so an archive that doesn't match is never installed. Linux and macOS: issue #11.
LLAMA_BUILDS = {
    ('windows', 'arm64'): ('bin-win-cpu-arm64.zip', 'ee0f631a9e58b146ff50714099d9cb498906af3143a773b580093a9214a8d1e5'),
    ('windows', 'x64'): ('bin-win-cpu-x64.zip', '1283323272b04cd07905816a597a0da810918102de958f4ff6f7bbaa70ed2efe'),
    ('linux', 'x64'): ('bin-ubuntu-x64.tar.gz', 'f6d25dde8f51133143d1453da4fd5f73b145127177612a283bf7995957af3392'),
    ('linux', 'arm64'): ('bin-ubuntu-arm64.tar.gz', 'ed44c0f79c3d02424f62bdc87e106318b0b89f49050e2e80c5f352723d14e00b'),
    ('macos', 'arm64'): ('bin-macos-arm64.tar.gz', '740288ec6887be94280a5dfa25b5e23a78285cab104519e6c7e218904ee82459'),
    ('macos', 'x64'): ('bin-macos-x64.tar.gz', '29ac3ea02be6bd143e824973f2cc5fa74bc4094393a9eaab0ff6814f19dd8522'),
}

def system_name(platform=None):
    platform = platform or sys.platform
    return 'windows' if platform == 'win32' else 'macos' if platform == 'darwin' else 'linux' if platform.startswith('linux') else platform

def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def check(path, expected, what):
    actual = sha256(path)
    if actual != expected:
        sys.exit(f'{what}: checksum mismatch\n  expected {expected}\n  got      {actual}\nDelete {path} and run again.')
    print(f'  {what}: verified')

def qwen():
    from huggingface_hub import hf_hub_download
    target = ROOT / QWEN['folder'] / QWEN['file']
    if not (target.exists() and sha256(target) == QWEN['sha256']):
        print('Downloading Qwen3.5-4B GGUF (~2.7 GB)...')
        hf_hub_download(QWEN['repo'], QWEN['file'], local_dir=ROOT / QWEN['folder'])
    check(target, QWEN['sha256'], 'Qwen3.5-4B Q4_K_M')

def smol():
    from huggingface_hub import snapshot_download
    folder = ROOT / SMOL['folder']
    weights = folder / 'model.safetensors'
    if not (weights.exists() and sha256(weights) == SMOL['weights_sha256']):
        print('Downloading SmolLM2-135M-Instruct (~270 MB)...')
        snapshot_download(SMOL['repo'], revision=SMOL['revision'], local_dir=folder,
                          allow_patterns=['*.json', '*.txt', '*.md', 'model.safetensors'])
    check(weights, SMOL['weights_sha256'], 'SmolLM2-135M-Instruct')

def minilm():
    """The small sentence-embedding model Friday uses to recall memories by meaning (optional: without it, recall
    falls back to matching words)."""
    from huggingface_hub import snapshot_download
    folder = ROOT / MINILM['folder']
    weights = folder / 'model.safetensors'
    if not (weights.exists() and sha256(weights) == MINILM['weights_sha256']):
        print('Downloading all-MiniLM-L6-v2 (~91 MB)...')
        snapshot_download(MINILM['repo'], revision=MINILM['revision'], local_dir=folder,
                          allow_patterns=['config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
                                          'vocab.txt', 'model.safetensors', 'README.md'])
    check(weights, MINILM['weights_sha256'], 'all-MiniLM-L6-v2')

def llama():
    sys.path.insert(0, str(ROOT / 'src'))
    from cpu_runtime import native_arch  # real CPU, even from an emulated x64 Python
    system, arch = system_name(), native_arch()
    build = LLAMA_BUILDS.get((system, arch))
    if not build:
        print(f'llama.cpp: no prebuilt {LLAMA_TAG} server for {system}/{arch}. Build llama-server '
              f'(https://github.com/ggml-org/llama.cpp) and put it in runtime/llama-{arch}/.')
        return
    asset, expected = build
    program = 'llama-server.exe' if system == 'windows' else 'llama-server'
    folder = ROOT / 'runtime' / f'llama-{arch}'
    if (folder / program).exists():
        print(f'  llama.cpp ({system} {arch}): present'); return
    url = f'https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/llama-{LLAMA_TAG}-{asset}'
    print(f'Downloading llama.cpp {LLAMA_TAG} for {system} {arch}...')
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        sys.exit(f'llama.cpp ({system} {arch}): checksum mismatch\n  expected {expected}\n  got      {actual}\nNothing was installed.')
    print(f'  llama.cpp ({system} {arch}): verified')
    staging = folder.with_name(folder.name + '-download')
    shutil.rmtree(staging, ignore_errors=True)
    if asset.endswith('.zip'):
        zipfile.ZipFile(io.BytesIO(data)).extractall(staging)
    else:
        # The Linux and macOS archives keep the server and its libraries (with symlinks) in one folder.
        # filter='data' refuses entries that would land outside the staging folder.
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            archive.extractall(staging, filter='data')
    server = next(staging.rglob(program))
    shutil.move(str(server.parent), str(folder))
    shutil.rmtree(staging, ignore_errors=True)
    if system != 'windows':
        (folder / program).chmod(0o755)
    print(f'  llama.cpp ({system} {arch}): installed to {folder.relative_to(ROOT)}')

if __name__ == '__main__':
    qwen(); smol(); minilm(); llama()
    print('Done. Start Friday with RUN.bat on Windows or ./run.sh on Linux and macOS.')
