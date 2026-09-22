# Serveur de décision Kev (https://github.com/jaredpalmer/kev) : modèle « Système 1 »
# exposant le contrat TypeSafe POST /v1/systemone (noul / choice / score).
FROM python:3.13-slim

# Commit amont figé pour des builds reproductibles.
ARG KEV_REF=0c0c9a6019dcc19b132b435e4393ffa771deda8a
# CPU par défaut (image légère). GPU NVIDIA : --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /opt/kev
RUN git init -q . && git fetch -q --depth 1 https://github.com/jaredpalmer/kev.git "$KEV_REF" && git checkout -q FETCH_HEAD

ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH UV_NO_CACHE=1
RUN uv venv -q /opt/venv \
  && uv pip install -q --index-url "$TORCH_INDEX" "torch==2.8.0" \
  && uv pip install -q -e ".[serve]"

COPY serve.py /opt/serve.py

# Les poids (adaptateur Kev + modèle de base Qwen) sont téléchargés au premier démarrage dans HF_HOME.
ENV HF_HOME=/data/hf KEV_RUN=jaredpalmer/kev-0.6b PORT=8008
VOLUME /data/hf
EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/v1/models' % os.environ['PORT'], timeout=4)"
CMD ["sh", "-c", "exec python /opt/serve.py --run \"$KEV_RUN\" --port \"$PORT\""]
