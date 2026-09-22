"""Penyusun graph ComfyUI (format API) untuk Qwen-Image 2.1 GGUF.

Node mengikuti template resmi Comfy-Org `image_qwen_image_2_1_t2i.json` dan
`image_qwen_image_2_1_image_edit.json`, dengan `UNETLoader` diganti
`UnetLoaderGGUF` dari custom node ComfyUI-GGUF.
"""

import os

UNET_NAME = os.getenv("QWEN_GGUF_NAME", "qwen-image-2.1-Q8_0.gguf")
CLIP_NAME = os.getenv("QWEN_CLIP_NAME", "qwen3vl_8b_int8_convrot.safetensors")
VAE_NAME = os.getenv("QWEN_VAE_NAME", "qwen_image_2.1_vae_bf16.safetensors")
SAMPLER = os.getenv("QWEN_SAMPLER", "euler")
SCHEDULER = os.getenv("QWEN_SCHEDULER", "simple")


def _model_nodes() -> dict:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET_NAME}},
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP_NAME, "type": "qwen_image", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}},
    }


def _latent_and_output_nodes(width: int, height: int, filename_prefix: str) -> dict:
    return {
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": filename_prefix},
        },
    }


def _sampler_node(steps: int, cfg: float, seed: int) -> dict:
    return {
        "class_type": "KSampler",
        "inputs": {
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["4", 1],
            "latent_image": ["5", 0],
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": SAMPLER,
            "scheduler": SCHEDULER,
            "denoise": 1.0,
        },
    }


def build_t2i(
    *,
    prompt: str,
    negative_prompt: str = "",
    steps: int = 40,
    cfg: float = 1.0,
    width: int = 1024,
    height: int = 1024,
    resolution: int = 1024,
    seed: int = 0,
    filename_prefix: str = "mapic",
) -> dict:
    """Text-to-image: tanpa gambar kondisi."""
    graph = _model_nodes()
    graph.update(_latent_and_output_nodes(width, height, filename_prefix))
    graph["4"] = {
        "class_type": "TextEncodeQwenImage21",
        "inputs": {
            "clip": ["2", 0],
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "resolution": resolution,
        },
    }
    graph["6"] = _sampler_node(steps, cfg, seed)
    return graph


def build_i2i(
    *,
    prompt: str,
    image_names: list[str],
    negative_prompt: str = "",
    steps: int = 40,
    cfg: float = 1.0,
    width: int = 1024,
    height: int = 1024,
    resolution: int = 1024,
    seed: int = 0,
    filename_prefix: str = "mapic",
) -> dict:
    """Image-to-image: 1-10 gambar referensi sebagai input `images.image_N`."""
    graph = _model_nodes()
    graph.update(_latent_and_output_nodes(width, height, filename_prefix))

    condition = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "resolution": resolution,
    }
    for index, name in enumerate(image_names, start=1):
        node_id = str(100 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        condition[f"images.image_{index}"] = [node_id, 0]

    graph["4"] = {"class_type": "TextEncodeQwenImage21", "inputs": condition}
    graph["6"] = _sampler_node(steps, cfg, seed)
    return graph
