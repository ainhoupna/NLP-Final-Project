# Model weights

Place your GGUF model file in this directory. The filename must match the
`LLM_MODEL_FILENAME` variable in your `.env` file.

## Recommended models

| Model | Size | RAM needed | Notes |
|---|---|---|---|
| `Llama-3.2-3B-Instruct-Q4_K_M.gguf` | ~2.0 GB | 4 GB | **Recommended** (fits 16GB RAM) |
| `Mistral-7B-Instruct-v0.2.Q4_K_M.gguf` | ~4.4 GB | 8 GB | Good all-rounder |
| `Llama-3.1-8B-Instruct.Q4_K_M.gguf` | ~4.9 GB | 8 GB | High quality |

## Download example

```bash
# Download Llama-3.2-3B (Recommended)
wget https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf -P ./models

# Then set in .env:
LLM_MODEL_FILENAME=Llama-3.2-3B-Instruct-Q4_K_M.gguf
```

> **Note:** Do not commit model files to git. This directory is listed in `.gitignore`.
