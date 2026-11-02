# Third-party components

Friday's own code (in `src/`, `tests/`, `tools/`, `scripts/`) is covered by this repository's `LICENSE`.
The components below are **not stored in this repository**. `scripts/download_models.py` fetches them from
their original publishers, and each stays under its own license. Licenses were checked on 2026-10-12.

| Component | Used for | License | Source |
|---|---|---|---|
| **Qwen3.5-4B** (Alibaba Qwen team), Q4_K_M GGUF conversion by **unsloth** | Writing Friday's replies | Apache License 2.0 | https://huggingface.co/Qwen/Qwen3.5-4B · https://huggingface.co/unsloth/Qwen3.5-4B-GGUF |
| **SmolLM2-135M-Instruct** (Hugging Face), revision `12fd25f7` | Frozen meaning features for the emotional appraisal | Apache License 2.0 | https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct |
| **all-MiniLM-L6-v2** (sentence-transformers, Hugging Face), revision `1110a243` | Recalling stored conversations by meaning | Apache License 2.0 | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |
| **llama.cpp** release `b11429` (commit `d8123504`), Windows CPU build | Runs the language model locally (`llama-server`) | MIT License, Copyright (c) 2023-2026 The ggml authors | https://github.com/ggml-org/llama.cpp |
| LLVM OpenMP runtime (`libomp.dll`, inside the llama.cpp ARM64 build) | Threading inside llama.cpp | Apache License 2.0 with LLVM Exceptions | https://openmp.llvm.org |

Python packages (installed from PyPI via `requirements.txt`, not redistributed):
PyTorch (BSD-3-Clause), Transformers (Apache-2.0), huggingface_hub (Apache-2.0), safetensors (Apache-2.0),
tokenizers (Apache-2.0), NumPy (BSD-3-Clause and others), plus their own dependencies.

`release/friday-base.pth` contains Friday's trained engine weights, which are this project's own work.
They are used together with the frozen SmolLM2 model above; SmolLM2's weights are not included in that file.

If you redistribute the downloaded models or runtime yourself, include their license texts: Apache-2.0 for the models, and the
MIT notice above for llama.cpp.
