# Serveur de décision Laya (https://huggingface.co/convaiinnovations/laya) : modèle
# « Système 1 » multilingue (français inclus), ~322M paramètres, exposé en POST /v1/systemone.
FROM python:3.12-slim

# CPU par défaut (~200 ms par question). GPU NVIDIA : --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --index-url "$TORCH_INDEX" "torch==2.14.0" \
  && pip install --no-cache-dir "laya==0.3.5" "transformers==5.17.0" "fastapi>=0.115" "uvicorn>=0.30"

WORKDIR /app
COPY server.py ./

# Les poids (~650 Mo) sont téléchargés au premier démarrage dans HF_HOME.
ENV HF_HOME=/data/hf LAYA_MODEL=convaiinnovations/laya LAYA_SUBFOLDER=multilingual PORT=8008 PYTHONUNBUFFERED=1
VOLUME /data/hf
EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/v1/models' % os.environ['PORT'], timeout=4)"
CMD ["python", "server.py"]
