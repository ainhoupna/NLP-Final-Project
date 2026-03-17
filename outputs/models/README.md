# Model weights — download instructions

The LLM service requires a GGUF quantised model file. These files are 2–8 GB and are **not** committed to this repository.

Place the downloaded file in this `models/` directory before running `docker-compose up`.

---

## Recommended models

### Option 1 — Mistral 7B Instruct v0.2 (recommended, 8 GB RAM minimum)

Best instruction-following quality for this task.

```bash
# Using huggingface-cli
pip install huggingface_hub
huggingface-cli download \
  TheBloke/Mistral-7B-Instruct-v0.2-GGUF \
  mistral-7b-instruct-v0.2.Q4_K_M.gguf \
  --local-dir ./models

# Or direct wget
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf \
  -O models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
```

### Option 2 — Llama 3.1 8B Instruct (strong multilingual)

```bash
huggingface-cli download \
  bartowski/Meta-Llama-3.1-8B-Instruct-GGUF \
  Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
  --local-dir ./models
```

### Option 3 — Qwen 2.5 3B Instruct (low memory, ≤ 6 GB RAM)

```bash
huggingface-cli download \
  Qwen/Qwen2.5-3B-Instruct-GGUF \
  qwen2.5-3b-instruct-q5_k_m.gguf \
  --local-dir ./models
```

---

## After downloading

Update the `command` field of the `llm` service in `docker-compose.yml` to match your chosen filename:

```yaml
command: >
  -m /models/YOUR_MODEL_FILENAME.gguf
  --host 0.0.0.0 --port 8080
  --ctx-size 4096 --n-predict 512
```

---

## Disk space summary

| Model | File size |
|---|---|
| Mistral 7B Q4_K_M | ~4.1 GB |
| Llama 3.1 8B Q4_K_M | ~4.7 GB |
| Qwen 2.5 3B Q5_K_M | ~2.0 GB |

> **Tip:** On slow connections, start the download before doing anything else. A 4 GB file at 10 MB/s takes ~7 minutes.
