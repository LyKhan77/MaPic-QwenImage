"""Uji kelayakan Qwen-Image 2.1 di server: VRAM puncak, timing, RGBA, multi-referensi.

Jalankan di server target dengan venv inference aktif:

    python smoke_test.py --resolution 1024 --steps 40 --refs 0

Hasilnya dipakai untuk mengisi tabel kalibrasi di
docs/superpowers/plans/2026-09-21-qwen-image-2.1-migration.md (Fase 0).
"""

import argparse
import json
import time

import torch
from diffusers import QwenImage21Pipeline
from PIL import Image


def vram_report(tag: str):
    for i in range(torch.cuda.device_count()):
        peak = torch.cuda.max_memory_allocated(i) / 1024**3
        total = torch.cuda.get_device_properties(i).total_memory / 1024**3
        print(f"[{tag}] GPU {i}: peak {peak:.2f} GB / total {total:.2f} GB")


def parse_max_memory(raw: str) -> dict:
    # accelerate expects integer GPU indices, but JSON object keys always come back as strings.
    parsed = json.loads(raw)
    return {int(k) if str(k).isdigit() else k: v for k, v in parsed.items()}


def device_map_report(pipe):
    """Show how much of the model landed on each device (CPU spill included)."""
    seen = {}
    for name in pipe.config.keys():
        module = getattr(pipe, name, None)
        if module is None or not hasattr(module, "parameters"):
            continue
        for param in module.parameters():
            dev = str(param.device)
            seen[dev] = seen.get(dev, 0) + param.numel()
    for dev in sorted(seen):
        print(f"  {dev}: {seen[dev] / 1e9:.2f}B params ({seen[dev] * 2 / 1e9:.2f} GB bf16)")
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--model", default="Qwen/Qwen-Image-2.1")
    parser.add_argument("--refs", type=int, default=0)
    parser.add_argument("--cfg-scale", type=float, default=1.0)
    parser.add_argument("--cpu-offload", action="store_true")
    parser.add_argument(
        "--max-memory",
        default=None,
        help='JSON batas memori per device, mis. {"cpu":"24GiB","0":"13GiB","1":"13GiB"}',
    )
    parser.add_argument("--output", default="smoke_out.png")
    args = parser.parse_args()

    print(f"Loading {args.model} (bf16)...")
    t0 = time.time()
    if args.cpu_offload:
        pipe = QwenImage21Pipeline.from_pretrained(args.model, torch_dtype=torch.bfloat16)
        pipe.enable_model_cpu_offload()
    elif args.max_memory:
        pipe = QwenImage21Pipeline.from_pretrained(
            args.model,
            torch_dtype=torch.bfloat16,
            device_map="balanced",
            max_memory=parse_max_memory(args.max_memory),
        )
    else:
        pipe = QwenImage21Pipeline.from_pretrained(
            args.model,
            torch_dtype=torch.bfloat16,
            device_map="balanced",
        )
    print(f"Load: {time.time() - t0:.1f}s")
    print("Sebaran parameter:")
    device_map_report(pipe)

    if hasattr(pipe.vae, "enable_slicing"):
        pipe.vae.enable_slicing()
    if hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
    vram_report("after_load")

    refs = None
    if args.refs:
        palette = [(200, 180, 160), (90, 140, 200), (170, 90, 120)]
        refs = [
            Image.new("RGB", (1024, 1024), palette[i % len(palette)])
            for i in range(args.refs)
        ]

    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    out = pipe(
        prompt="A ceramic teapot on a wooden table, morning light",
        image=refs,
        negative_prompt="blurry, low quality" if args.cfg_scale > 1 else None,
        true_cfg_scale=args.cfg_scale,
        width=args.resolution,
        height=args.resolution,
        output_resolution=args.resolution,
        num_inference_steps=args.steps,
    ).images[0]
    elapsed = time.time() - t0
    print(
        f"Generate {args.resolution}px steps={args.steps} refs={args.refs} "
        f"cfg={args.cfg_scale}: {elapsed:.1f}s"
    )
    vram_report("after_generate")

    out.save(args.output)
    print(f"Saved {args.output} mode={out.mode} size={out.size}")


if __name__ == "__main__":
    main()
