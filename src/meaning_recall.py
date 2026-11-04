"""Recall by meaning (stage M1, better recall; write-up in docs/m1-recall-by-meaning.md).

Word overlap missed most memories ("what did I say about my health?" never matched "the doctor said my blood pressure
is too high") and once matched the wrong one on a filler word. A small sentence-embedding model (all-MiniLM-L6-v2,
Apache-2.0, ~91 MB, fetched by scripts/download_models.py) puts the right memory in the top three for 14 of 16 test
questions, against 5 of 16 for word overlap.

It must not slow replies. The model loads in a background thread at start; the newest message is embedded on a
worker thread while the language model is busy interpreting it (about 10 ms of work); stored exchanges are
embedded after the reply is shown. Without the model files everything falls back to word overlap.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / 'data/models/all-minilm-l6-v2'
MODEL_TAG = 'all-MiniLM-L6-v2@1110a243'  # vectors from another model or revision aren't comparable


class MeaningIndex:
    def __init__(self, folder=MODEL_DIR):
        self.folder = Path(folder)
        self._model = self._tokenizer = None
        self._loaded = threading.Event()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='meaning')
        self.available = (self.folder / 'model.safetensors').exists()
        if self.available:
            self._worker.submit(self._load)
        else:
            self._loaded.set()

    def _load(self):
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
            from transformers.utils import logging as hf_logging
            hf_logging.set_verbosity_error()
            self._tokenizer = AutoTokenizer.from_pretrained(self.folder)
            self._model = AutoModel.from_pretrained(self.folder).eval()
            with torch.no_grad():
                self._embed(['warm up'])
        except Exception:  # a broken download must not stop Friday; recall falls back to word overlap
            self.available = False
        finally:
            self._loaded.set()

    def _embed(self, texts):
        import torch
        import torch.nn.functional as F
        with torch.no_grad():
            batch = self._tokenizer(list(texts), padding=True, truncation=True, max_length=128, return_tensors='pt')
            hidden = self._model(**batch).last_hidden_state
            mask = batch['attention_mask'].unsqueeze(-1).float()
            return F.normalize((hidden * mask).sum(1) / mask.sum(1), dim=1)

    def embed(self, texts, wait=True):
        """Unit vectors for the texts (a float32 tensor, one row each), or None when the model isn't available.
        With wait=False it returns None instead of waiting for the model to finish loading."""
        if not self.available or (not wait and not self._loaded.is_set()):
            return None
        self._loaded.wait()
        if not self.available or self._model is None:
            return None
        return self._embed(texts)

    def embed_later(self, text):
        """Start embedding one message on the worker thread; .result() gives its vector (or None)."""
        return self._worker.submit(lambda: (lambda v: None if v is None else v[0])(self.embed([text])))


_INDEX = None


def index():
    """The shared index, created (and its model load started) on first use."""
    global _INDEX
    if _INDEX is None:
        _INDEX = MeaningIndex()
    return _INDEX
