FROM python:3.12-slim

# Facade adalah klien HTTP ComfyUI — tidak butuh torch sama sekali,
# sehingga image tetap kecil dan cepat dibangun.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY qwen_image_server/requirements-facade.txt /app/requirements-facade.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements-facade.txt

COPY qwen_image_server/ /app/

EXPOSE 30000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "30000"]
