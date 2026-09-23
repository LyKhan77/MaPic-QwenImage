FROM pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime

# Torch sudah ada di base image dengan versi yang sama seperti host (2.11.0+cu130),
# jadi langkah ini hanya menambah dependensi ComfyUI.
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# Commit dipin supaya build dapat direproduksi.
ARG COMFYUI_COMMIT=e638023
ARG GGUF_NODE_COMMIT=edd981b

RUN git clone https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI \
    && git -C /opt/ComfyUI checkout ${COMFYUI_COMMIT} \
    && git clone https://github.com/leejet/ComfyUI-GGUF.git /opt/ComfyUI/custom_nodes/ComfyUI-GGUF \
    && git -C /opt/ComfyUI/custom_nodes/ComfyUI-GGUF checkout ${GGUF_NODE_COMMIT}

WORKDIR /opt/ComfyUI

# Base image memakai Python sistem dengan penanda PEP 668 (externally managed),
# sehingga pip menolak memasang ke sistem. Venv dengan --system-site-packages
# memakai torch bawaan image tetapi tetap bisa memasang dependensi ComfyUI.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv --system-site-packages ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python -c "import torch; print('torch dari base image:', torch.__version__)"

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt && pip install gguf

# Model tidak dibakar ke image: di-mount read-only lewat file ini.
COPY extra_model_paths.yaml /opt/ComfyUI/extra_model_paths.yaml

EXPOSE 8188
CMD ["python", "main.py", \
     "--listen", "0.0.0.0", \
     "--port", "8188", \
     "--lowvram", \
     "--extra-model-paths-config", "/opt/ComfyUI/extra_model_paths.yaml"]
