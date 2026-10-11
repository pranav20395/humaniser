"""Download a GGUF file of jialinyyzz/humanizer from Hugging Face."""

import os
import sys
from pathlib import Path

REPO = "jialinyyzz/humanizer"

# name -> (file size in bytes, minimum memory in GiB), from the model card.
QUANTS = {
    "Q8_0": (12_669_630_368, 30),       # recommended, best quality: 32 GB machines
    "Q6_K": (10_029_799_584, 15),       # 16 GB, no measurable loss
    "Q4_K_M": (7_625_160_864, 13),      # about 14 GB, slight loss
    "Q3-QAT": (5_587_794_816, 11),      # 12 GB, a few more fact slips
    "IQ2_XS-QAT": (3_893_632_896, 7),   # 8 GB, 2-bit, the smallest
}


def filename(quant: str) -> str:
    return f"humanizer-12b-{quant}.gguf"


def memory_gib() -> float | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return None


def pick_quant(mem: float | None) -> str:
    if mem is None:
        return "Q4_K_M"
    for quant, (_, need) in QUANTS.items():
        if mem >= need:
            return quant
    sys.exit(f"error: {mem:.0f} GiB of memory is not enough for the 12B model (8 GB is the minimum).")


def download(quant: str, directory: Path) -> Path:
    from huggingface_hub import hf_hub_download

    if quant == "auto":
        mem = memory_gib()
        quant = pick_quant(mem)
        print(f"{mem:.0f} GiB of memory: picked {quant}" if mem else f"memory unknown: picked {quant}",
              file=sys.stderr)
    if quant not in QUANTS:
        sys.exit(f"error: unknown quant {quant!r}; choose from {', '.join(QUANTS)}")
    size = QUANTS[quant][0]
    print(f"downloading {filename(quant)} ({size / 1e9:.1f} GB) from {REPO} into {directory}/", file=sys.stderr)
    path = Path(hf_hub_download(REPO, filename(quant), local_dir=directory))
    if path.stat().st_size != size:
        sys.exit(f"error: {path} is {path.stat().st_size} bytes, expected {size}. Delete it and download again.")
    return path
