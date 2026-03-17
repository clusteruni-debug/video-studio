"""Download FLUX.1-schnell large blobs via urllib with chunked resume."""
import os
import sys
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_url
from urllib.request import urlopen, Request

REPO = "black-forest-labs/FLUX.1-schnell"
CACHE = Path.home() / ".cache" / "huggingface" / "hub" / "models--black-forest-labs--FLUX.1-schnell"
BLOBS = CACHE / "blobs"
TOKEN = os.environ.get("HF_TOKEN", "")

api = HfApi()
files = api.model_info(REPO).siblings

# Find incomplete blobs
incomplete = [f for f in BLOBS.glob("*.incomplete")]
print(f"Found {len(incomplete)} incomplete blobs")

for inc in sorted(incomplete, key=lambda p: p.stat().st_size):
    target_hash = inc.stem  # hash without .incomplete
    current_size = inc.stat().st_size
    print(f"\nResuming {target_hash[:16]}... ({current_size / 1e9:.1f} GB downloaded)")

    # Find which repo file matches this blob hash
    matched = None
    for f in files:
        url = hf_hub_url(REPO, f.rfilename)
        if f.lfs and f.lfs.get("sha256") == target_hash:
            matched = f
            break

    if not matched:
        print(f"  Could not match blob to repo file, skipping")
        continue

    url = hf_hub_url(REPO, matched.rfilename)
    total = matched.lfs["size"] if matched.lfs else 0
    print(f"  File: {matched.rfilename} ({total / 1e9:.1f} GB total)")
    print(f"  Remaining: {(total - current_size) / 1e9:.1f} GB")

    headers = {"Range": f"bytes={current_size}-"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=300) as resp, open(inc, "ab") as fout:
            downloaded = 0
            while True:
                chunk = resp.read(8 * 1024 * 1024)  # 8MB chunks
                if not chunk:
                    break
                fout.write(chunk)
                downloaded += len(chunk)
                total_now = current_size + downloaded
                pct = (total_now / total * 100) if total else 0
                sys.stdout.write(f"\r  {total_now / 1e9:.2f} / {total / 1e9:.2f} GB ({pct:.1f}%)")
                sys.stdout.flush()

        print(f"\n  Complete! Renaming...")
        final = BLOBS / target_hash
        inc.rename(final)
        print(f"  OK: {final.name}")

    except Exception as e:
        print(f"\n  Error: {e}")
        print(f"  Progress saved — rerun to resume")

print("\nAll done. Run flux-test.py to generate image.")
