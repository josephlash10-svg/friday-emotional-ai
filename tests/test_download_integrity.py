"""llama.cpp holds the programs Friday runs, so its download must match the pinned release digest (2026-10-19).
Linux and macOS builds added for issue #11 (2026-10-21)."""
import hashlib
import importlib.util
import io
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import cpu_runtime  # noqa: F401  (download_models imports native_arch from it)

spec = importlib.util.spec_from_file_location('download_models', ROOT / 'scripts' / 'download_models.py')
dm = importlib.util.module_from_spec(spec); spec.loader.exec_module(dm)


def windows_release():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('build/bin/llama-server.exe', b'not really a server')
    return buffer.getvalue()


def unix_release():
    """Same shape as the real Linux/macOS archives: one folder, the server, a library and a symlink to it."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, data in (('llama-b11429/llama-server', b'not really a server'), ('llama-b11429/libllama.so.0.6.0', b'lib')):
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo('llama-b11429/libllama.so'); link.type = tarfile.SYMTYPE; link.linkname = 'libllama.so.0.6.0'
        archive.addfile(link)
    return buffer.getvalue()


class Download:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.data


class LlamaDownloadIntegrityTests(unittest.TestCase):
    def run_download(self, system, data, pinned):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        asset = dict(dm.LLAMA_BUILDS)[(system, 'arm64')][0]
        with patch.object(dm, 'ROOT', root), patch.object(dm.urllib.request, 'urlopen', lambda url, timeout=None: Download(data)), \
             patch.object(cpu_runtime, 'native_arch', lambda: 'arm64'), patch.object(dm, 'system_name', lambda: system), \
             patch.dict(dm.LLAMA_BUILDS, {(system, 'arm64'): (asset, pinned)}), patch('builtins.print'):
            try:
                dm.llama(); error = None
            except SystemExit as stop:
                error = stop
        return root, error

    def test_a_tampered_download_is_never_installed(self):
        for system, data in (('windows', windows_release()), ('linux', unix_release())):
            root, error = self.run_download(system, data, pinned='0' * 64)
            self.assertIn('checksum mismatch', str(error), system)
            self.assertFalse((root / 'runtime').exists(), system)

    def test_a_matching_windows_download_is_installed(self):
        data = windows_release()
        root, error = self.run_download('windows', data, pinned=hashlib.sha256(data).hexdigest())
        self.assertIsNone(error)
        self.assertTrue((root / 'runtime' / 'llama-arm64' / 'llama-server.exe').is_file())

    def test_a_matching_linux_or_macos_download_keeps_its_libraries(self):
        data = unix_release()
        root, error = self.run_download('linux', data, pinned=hashlib.sha256(data).hexdigest())
        self.assertIsNone(error)
        folder = root / 'runtime' / 'llama-arm64'
        self.assertTrue((folder / 'llama-server').is_file())
        self.assertTrue((folder / 'libllama.so.0.6.0').is_file())
        self.assertTrue((folder / 'libllama.so').exists() or (folder / 'libllama.so').is_symlink())

    def test_every_published_build_is_pinned(self):
        self.assertEqual(set(dm.LLAMA_BUILDS), {(s, a) for s in ('windows', 'linux', 'macos') for a in ('x64', 'arm64')})
        self.assertTrue(all(len(sha) == 64 for _, sha in dm.LLAMA_BUILDS.values()))
        self.assertEqual([dm.system_name(p) for p in ('win32', 'linux', 'darwin')], ['windows', 'linux', 'macos'])


class RuntimePathTests(unittest.TestCase):
    def test_server_name_per_platform(self):
        self.assertEqual(cpu_runtime.runtime_path('x64', windows=True).name, 'llama-server.exe')
        self.assertEqual(cpu_runtime.runtime_path('arm64', windows=False).name, 'llama-server')
        self.assertEqual(cpu_runtime.runtime_path('arm64', windows=False).parent.name, 'llama-arm64')

    def test_linux_server_is_tied_to_friday(self):
        self.assertTrue(callable(cpu_runtime.die_with_parent))


if __name__ == '__main__':
    unittest.main()
