FROM erew123/alltalk_tts:latest

ENV TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -m pip uninstall -y torch torchaudio || true; \
    python3 -m pip install --no-cache-dir --upgrade --force-reinstall \
      torch==2.7.1+cu128 torchaudio==2.7.1+cu128 \
      --index-url https://download.pytorch.org/whl/cu128; \
    python3 -m pip install --no-cache-dir "networkx<3"
