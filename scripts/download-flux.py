import os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

from huggingface_hub import snapshot_download

print("Downloading FLUX.1-schnell (single-thread, resume-enabled)...")
snapshot_download(
    "black-forest-labs/FLUX.1-schnell",
    local_files_only=False,
    resume_download=True,
    max_workers=1,
)
print("DOWNLOAD COMPLETE")
