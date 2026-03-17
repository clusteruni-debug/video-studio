"""Clean incomplete cache and re-download FLUX.1-schnell one file at a time."""
import os
import shutil
from pathlib import Path
from huggingface_hub import hf_hub_download

os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

REPO = "black-forest-labs/FLUX.1-schnell"
CACHE = Path.home() / ".cache" / "huggingface" / "hub" / "models--black-forest-labs--FLUX.1-schnell"

# Remove incomplete blobs
blobs = CACHE / "blobs"
if blobs.exists():
    for f in blobs.glob("*.incomplete"):
        print(f"Removing incomplete: {f.name[:20]}... ({f.stat().st_size / 1e9:.1f} GB)")
        f.unlink()

# Files to download (largest safetensor shards + key files)
FILES = [
    "model_index.json",
    "scheduler/scheduler_config.json",
    "text_encoder/config.json",
    "text_encoder/model.safetensors",
    "text_encoder_2/config.json",
    "text_encoder_2/model-00001-of-00002.safetensors",
    "text_encoder_2/model-00002-of-00002.safetensors",
    "text_encoder_2/model.safetensors.index.json",
    "tokenizer/merges.txt",
    "tokenizer/special_tokens_map.json",
    "tokenizer/tokenizer_config.json",
    "tokenizer/vocab.json",
    "tokenizer_2/special_tokens_map.json",
    "tokenizer_2/spiece.model",
    "tokenizer_2/tokenizer.json",
    "tokenizer_2/tokenizer_config.json",
    "transformer/config.json",
    "transformer/diffusion_pytorch_model-00001-of-00003.safetensors",
    "transformer/diffusion_pytorch_model-00002-of-00003.safetensors",
    "transformer/diffusion_pytorch_model-00003-of-00003.safetensors",
    "transformer/diffusion_pytorch_model.safetensors.index.json",
    "vae/config.json",
    "vae/diffusion_pytorch_model.safetensors",
]

print(f"\nDownloading {len(FILES)} files one by one...\n")

for i, fname in enumerate(FILES, 1):
    print(f"[{i}/{len(FILES)}] {fname}", end=" ... ", flush=True)
    try:
        hf_hub_download(
            repo_id=REPO,
            filename=fname,
            resume_download=True,
        )
        print("OK")
    except Exception as e:
        print(f"FAILED: {e}")
        print("Re-run this script to resume from where it stopped.")
        break

print("\nDone. Run: .venv\\Scripts\\python.exe scripts\\flux-test.py")
